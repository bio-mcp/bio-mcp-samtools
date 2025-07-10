"""
Enhanced Samtools MCP server with intelligent tool detection.

This server can automatically detect and use Samtools from:
- Native installations (PATH)
- Environment Modules
- Lmod modules
- Singularity containers
- Docker containers
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ErrorContent
from pydantic_settings import BaseSettings

from .tool_detection import ToolDetector, ToolConfig, ExecutionMode, ToolInfo

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = 10_000_000_000  # 10GB for BAM files
    temp_dir: Optional[str] = None
    timeout: int = 1800  # 30 minutes for large files
    
    # Tool execution mode settings
    execution_mode: Optional[str] = None
    preferred_modes: str = "native,module,lmod,singularity,docker"
    module_names: str = "samtools,SAMtools"
    container_image: str = "biocontainers/samtools:1.19.2"
    
    class Config:
        env_prefix = "BIO_MCP_"


class SamtoolsServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-samtools")
        self.detector = ToolDetector(logger)
        self.tool_config = ToolConfig.from_env()
        self.samtools_info = None
        self._setup_handlers()
        
    async def _detect_samtools(self) -> ToolInfo:
        """Detect the best available execution mode for samtools."""
        if self.samtools_info is not None:
            return self.samtools_info
        
        # Parse settings
        force_mode = None
        if self.settings.execution_mode:
            try:
                force_mode = ExecutionMode(self.settings.execution_mode.lower())
            except ValueError:
                logger.warning(f"Invalid execution mode: {self.settings.execution_mode}")
        
        preferred_modes = []
        for mode_str in self.settings.preferred_modes.split(","):
            try:
                mode = ExecutionMode(mode_str.strip().lower())
                preferred_modes.append(mode)
            except ValueError:
                logger.warning(f"Invalid preferred mode: {mode_str}")
        
        module_names = [name.strip() for name in self.settings.module_names.split(",")]
        
        # Detect tool
        self.samtools_info = self.detector.detect_tool(
            tool_name="samtools",
            module_names=module_names,
            container_image=self.settings.container_image,
            preferred_modes=preferred_modes or None,
            force_mode=force_mode
        )
        
        return self.samtools_info
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="samtools_view",
                    description="View/convert SAM/BAM/CRAM files with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to SAM/BAM/CRAM file"
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["sam", "bam", "cram"],
                                "default": "bam",
                                "description": "Output format"
                            },
                            "region": {
                                "type": "string",
                                "description": "Region to extract (e.g., chr1:1000-2000)"
                            },
                            "flags_include": {
                                "type": "integer",
                                "description": "Include reads with all these flags"
                            },
                            "flags_exclude": {
                                "type": "integer",
                                "description": "Exclude reads with any of these flags"
                            },
                            "quality_min": {
                                "type": "integer",
                                "description": "Minimum mapping quality"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_sort",
                    description="Sort SAM/BAM files with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to SAM/BAM file"
                            },
                            "sort_by": {
                                "type": "string",
                                "enum": ["coordinate", "name"],
                                "default": "coordinate",
                                "description": "Sort by coordinate or read name"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 1,
                                "description": "Number of threads"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_index",
                    description="Index BAM/CRAM files with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to BAM/CRAM file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_stats",
                    description="Generate statistics from SAM/BAM/CRAM files",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to SAM/BAM/CRAM file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_flagstat",
                    description="Generate flagstat summary from SAM/BAM/CRAM files",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to SAM/BAM/CRAM file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_info",
                    description="Get information about samtools tool detection and execution mode",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ErrorContent]:
            if name == "samtools_view":
                return await self._run_view(arguments)
            elif name == "samtools_sort":
                return await self._run_sort(arguments)
            elif name == "samtools_index":
                return await self._run_index(arguments)
            elif name == "samtools_stats":
                return await self._run_stats(arguments)
            elif name == "samtools_flagstat":
                return await self._run_flagstat(arguments)
            elif name == "samtools_info":
                return await self._get_samtools_info()
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _get_samtools_info(self) -> list[TextContent]:
        """Get information about samtools tool detection."""
        tool_info = await self._detect_samtools()
        
        info = {
            "tool_name": "samtools",
            "execution_mode": tool_info.mode.value,
            "available": tool_info.mode != ExecutionMode.UNAVAILABLE,
            "path": tool_info.path,
            "version": tool_info.version,
            "module_name": tool_info.module_name,
            "container_image": tool_info.container_image,
            "settings": {
                "execution_mode": self.settings.execution_mode,
                "preferred_modes": self.settings.preferred_modes.split(","),
                "module_names": self.settings.module_names.split(","),
                "container_image": self.settings.container_image
            }
        }
        
        return [TextContent(text=f"Samtools Tool Detection Info:\\n{info}")]
    
    async def _execute_samtools_command(self, subcommand: str, tool_args: list[str], tmpdir: str) -> tuple[bytes, bytes, int]:
        """Execute a samtools command with intelligent tool detection."""
        # Detect samtools tool
        tool_info = await self._detect_samtools()
        if tool_info.mode == ExecutionMode.UNAVAILABLE:
            raise RuntimeError("samtools is not available in any execution mode")
        
        # Build complete command
        full_args = [subcommand] + tool_args
        cmd = self.detector.get_execution_command(tool_info, full_args)
        
        logger.info(f"Executing samtools {subcommand} via {tool_info.mode.value}: {' '.join(cmd)}")
        
        # Execute command
        if tool_info.mode in [ExecutionMode.MODULE, ExecutionMode.LMOD]:
            # Module commands need to be executed in shell
            shell_cmd = " ".join(cmd)
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir
            )
        else:
            # Direct execution for native, container modes
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir
            )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.settings.timeout
        )
        
        return stdout, stderr, process.returncode
    
    async def _run_view(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run samtools view with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_file = Path(tmpdir) / f"output.{arguments.get('output_format', 'bam')}"
                
                # Build samtools view arguments
                tool_args = []
                
                # Output format
                format_flag = {
                    "sam": "-h",
                    "bam": "-b", 
                    "cram": "-C"
                }
                tool_args.append(format_flag.get(arguments.get("output_format", "bam"), "-b"))
                
                # Filters
                if arguments.get("flags_include"):
                    tool_args.extend(["-f", str(arguments["flags_include"])])
                if arguments.get("flags_exclude"):
                    tool_args.extend(["-F", str(arguments["flags_exclude"])])
                if arguments.get("quality_min"):
                    tool_args.extend(["-q", str(arguments["quality_min"])])
                
                # Output file
                tool_args.extend(["-o", str(output_file)])
                
                # Input file
                tool_args.append(str(input_file))
                
                # Region
                if arguments.get("region"):
                    tool_args.append(arguments["region"])
                
                # Execute command
                stdout, stderr, returncode = await self._execute_samtools_command("view", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"samtools view failed: {stderr.decode()}")]
                
                # Read output file
                if output_file.exists():
                    with open(output_file, 'rb') as f:
                        content = f.read()
                    return [TextContent(text=f"Output saved to {output_file}\\nFile size: {len(content)} bytes")]
                else:
                    return [TextContent(text=stdout.decode())]
                    
        except Exception as e:
            logger.error(f"Error running samtools view: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_sort(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run samtools sort with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_file = Path(tmpdir) / "sorted.bam"
                
                # Build samtools sort arguments
                tool_args = []
                
                # Sort type
                if arguments.get("sort_by") == "name":
                    tool_args.append("-n")
                
                # Threads
                tool_args.extend(["-@", str(arguments.get("threads", 1))])
                
                # Output file
                tool_args.extend(["-o", str(output_file)])
                
                # Input file
                tool_args.append(str(input_file))
                
                # Execute command
                stdout, stderr, returncode = await self._execute_samtools_command("sort", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"samtools sort failed: {stderr.decode()}")]
                
                # Read output file
                if output_file.exists():
                    with open(output_file, 'rb') as f:
                        content = f.read()
                    return [TextContent(text=f"File sorted successfully\\nOutput size: {len(content)} bytes")]
                else:
                    return [TextContent(text=stdout.decode())]
                    
        except Exception as e:
            logger.error(f"Error running samtools sort: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_index(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run samtools index with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                # Copy input file to temp directory
                temp_input = Path(tmpdir) / input_file.name
                temp_input.write_bytes(input_file.read_bytes())
                
                # Build samtools index arguments
                tool_args = [str(temp_input)]
                
                # Execute command
                stdout, stderr, returncode = await self._execute_samtools_command("index", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"samtools index failed: {stderr.decode()}")]
                
                return [TextContent(text=f"Index created successfully\\n{stdout.decode()}")]
                    
        except Exception as e:
            logger.error(f"Error running samtools index: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_stats(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run samtools stats with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                # Build samtools stats arguments
                tool_args = [str(input_file)]
                
                # Execute command
                stdout, stderr, returncode = await self._execute_samtools_command("stats", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"samtools stats failed: {stderr.decode()}")]
                
                return [TextContent(text=stdout.decode())]
                    
        except Exception as e:
            logger.error(f"Error running samtools stats: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_flagstat(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run samtools flagstat with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                # Build samtools flagstat arguments
                tool_args = [str(input_file)]
                
                # Execute command
                stdout, stderr, returncode = await self._execute_samtools_command("flagstat", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"samtools flagstat failed: {stderr.decode()}")]
                
                return [TextContent(text=stdout.decode())]
                    
        except Exception as e:
            logger.error(f"Error running samtools flagstat: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream)


async def main():
    logging.basicConfig(level=logging.INFO)
    server = SamtoolsServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())