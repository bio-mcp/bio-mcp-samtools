import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ErrorContent
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = 10_000_000_000  # 10GB for BAM files
    temp_dir: Optional[str] = None
    timeout: int = 1800  # 30 minutes for large files
    samtools_path: str = "samtools"
    
    class Config:
        env_prefix = "BIO_MCP_"


class SamtoolsServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-samtools")
        self._setup_handlers()
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="samtools_view",
                    description="View/convert SAM/BAM/CRAM files",
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
                    description="Sort SAM/BAM files",
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
                                "description": "Sort order"
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["sam", "bam", "cram"],
                                "default": "bam"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_index",
                    description="Create index for BAM/CRAM files",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to sorted BAM/CRAM file"
                            },
                            "index_type": {
                                "type": "string",
                                "enum": ["bai", "csi"],
                                "default": "bai",
                                "description": "Index type"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_stats",
                    description="Generate alignment statistics",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to BAM file"
                            },
                            "region": {
                                "type": "string",
                                "description": "Region to analyze"
                            },
                            "reference": {
                                "type": "string",
                                "description": "Reference FASTA file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_flagstat",
                    description="Count reads in each FLAG category",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to BAM file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="samtools_depth",
                    description="Calculate per-position depth",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to BAM file"
                            },
                            "region": {
                                "type": "string",
                                "description": "Region to analyze"
                            },
                            "max_depth": {
                                "type": "integer",
                                "default": 8000,
                                "description": "Maximum depth to report"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ErrorContent]:
            handlers = {
                "samtools_view": self._run_view,
                "samtools_sort": self._run_sort,
                "samtools_index": self._run_index,
                "samtools_stats": self._run_stats,
                "samtools_flagstat": self._run_flagstat,
                "samtools_depth": self._run_depth,
            }
            
            handler = handlers.get(name)
            if handler:
                return await handler(arguments)
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _run_view(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_file = Path(tmpdir) / f"output.{arguments.get('output_format', 'bam')}"
                
                cmd = [self.settings.samtools_path, "view"]
                
                # Output format
                format_flag = {
                    "sam": "-h",
                    "bam": "-b",
                    "cram": "-C"
                }
                cmd.append(format_flag.get(arguments.get("output_format", "bam"), "-b"))
                
                # Filters
                if arguments.get("flags_include"):
                    cmd.extend(["-f", str(arguments["flags_include"])])
                if arguments.get("flags_exclude"):
                    cmd.extend(["-F", str(arguments["flags_exclude"])])
                if arguments.get("quality_min"):
                    cmd.extend(["-q", str(arguments["quality_min"])])
                
                # Output file
                cmd.extend(["-o", str(output_file)])
                
                # Input file
                cmd.append(str(input_file))
                
                # Region
                if arguments.get("region"):
                    cmd.append(arguments["region"])
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.settings.timeout
                )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"samtools view failed: {stderr.decode()}")]
                
                # Get file stats
                output_size = output_file.stat().st_size if output_file.exists() else 0
                
                return [TextContent(
                    text=f"View operation completed successfully!\n\n"
                         f"Output file: {output_file}\n"
                         f"Output size: {output_size:,} bytes\n"
                         f"Command: {' '.join(cmd)}"
                )]
                
        except Exception as e:
            logger.error(f"Error in samtools view: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_sort(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_file = Path(tmpdir) / f"sorted.{arguments.get('output_format', 'bam')}"
                
                cmd = [
                    self.settings.samtools_path, "sort",
                    "-o", str(output_file)
                ]
                
                # Sort order
                if arguments.get("sort_by") == "name":
                    cmd.append("-n")
                
                # Output format
                output_format = arguments.get("output_format", "bam")
                if output_format == "sam":
                    cmd.append("-O SAM")
                elif output_format == "cram":
                    cmd.append("-O CRAM")
                
                cmd.append(str(input_file))
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.settings.timeout
                )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"samtools sort failed: {stderr.decode()}")]
                
                output_size = output_file.stat().st_size if output_file.exists() else 0
                
                return [TextContent(
                    text=f"Sort completed successfully!\n\n"
                         f"Output file: {output_file}\n"
                         f"Output size: {output_size:,} bytes\n"
                         f"Sort order: {arguments.get('sort_by', 'coordinate')}\n"
                         f"Format: {output_format}"
                )]
                
        except Exception as e:
            logger.error(f"Error in samtools sort: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_stats(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            cmd = [self.settings.samtools_path, "stats"]
            
            if arguments.get("reference"):
                cmd.extend(["--reference", arguments["reference"]])
            
            cmd.append(str(input_file))
            
            if arguments.get("region"):
                cmd.append(arguments["region"])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return [ErrorContent(text=f"samtools stats failed: {stderr.decode()}")]
            
            return [TextContent(text=stdout.decode())]
            
        except Exception as e:
            logger.error(f"Error in samtools stats: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_flagstat(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            cmd = [self.settings.samtools_path, "flagstat", str(input_file)]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return [ErrorContent(text=f"samtools flagstat failed: {stderr.decode()}")]
            
            return [TextContent(text=f"Flagstat Results:\n\n{stdout.decode()}")]
            
        except Exception as e:
            logger.error(f"Error in samtools flagstat: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_index(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            cmd = [self.settings.samtools_path, "index"]
            
            if arguments.get("index_type") == "csi":
                cmd.append("-c")
            
            cmd.append(str(input_file))
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return [ErrorContent(text=f"samtools index failed: {stderr.decode()}")]
            
            index_ext = "csi" if arguments.get("index_type") == "csi" else "bai"
            index_file = input_file.with_suffix(f".{index_ext}")
            
            return [TextContent(
                text=f"Index created successfully!\n\n"
                     f"Index file: {index_file}\n"
                     f"Index type: {index_ext.upper()}"
            )]
            
        except Exception as e:
            logger.error(f"Error in samtools index: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_depth(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            cmd = [
                self.settings.samtools_path, "depth",
                "-d", str(arguments.get("max_depth", 8000)),
                str(input_file)
            ]
            
            if arguments.get("region"):
                cmd.extend(["-r", arguments["region"]])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return [ErrorContent(text=f"samtools depth failed: {stderr.decode()}")]
            
            # Parse depth output for summary
            lines = stdout.decode().strip().split('\n')
            if lines and lines[0]:
                depths = [int(line.split('\t')[2]) for line in lines if line]
                avg_depth = sum(depths) / len(depths) if depths else 0
                max_depth = max(depths) if depths else 0
                
                summary = f"Depth Analysis Summary:\n"
                summary += f"Positions analyzed: {len(depths):,}\n"
                summary += f"Average depth: {avg_depth:.2f}\n"
                summary += f"Maximum depth: {max_depth}\n\n"
                
                # Show first 20 lines of output
                preview = '\n'.join(lines[:20])
                if len(lines) > 20:
                    preview += f"\n... ({len(lines)-20} more lines)"
                
                return [TextContent(text=summary + "Per-position depth:\n" + preview)]
            else:
                return [TextContent(text="No depth data found")]
            
        except Exception as e:
            logger.error(f"Error in samtools depth: {e}", exc_info=True)
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