# bio-mcp-samtools

MCP (Model Context Protocol) server for Samtools, a suite of utilities for interacting with high-throughput sequencing data in SAM, BAM, and CRAM formats.

## Overview

This MCP server provides access to various Samtools functionalities, enabling AI assistants to perform operations like viewing, sorting, indexing, and generating statistics for alignment files.

## Features

- **samtools_view**: View and convert SAM/BAM/CRAM files.
- **samtools_sort**: Sort SAM/BAM files by coordinate or read name.
- **samtools_index**: Create indexes for sorted BAM/CRAM files.
- **samtools_stats**: Generate comprehensive alignment statistics.
- **samtools_flagstat**: Count reads in each FLAG category.
- **samtools_depth**: Calculate per-position read depth.

## Installation

### Prerequisites

- Python 3.9+
- Samtools installed (`samtools`)

### Install Samtools

```bash
# macOS
brew install samtools

# Ubuntu/Debian
sudo apt-get install samtools

# From conda
conda install -c bioconda samtools
```

### Install the MCP server

```bash
git clone https://github.com/bio-mcp/bio-mcp-samtools
cd bio-mcp-samtools
pip install -e .
```

## Configuration

Add to your MCP client configuration (e.g., Claude Desktop `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bio-samtools": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/bio-mcp-samtools"
    }
  }
}
```

### Environment Variables

- `BIO_MCP_MAX_FILE_SIZE`: Maximum input file size in bytes (default: 10GB)
- `BIO_MCP_TIMEOUT`: Command timeout in seconds (default: 1800)
- `BIO_MCP_SAMTOOLS_PATH`: Path to Samtools executable (default: finds in PATH)
- `BIO_MCP_TEMP_DIR`: Temporary directory for processing

## Usage

Once configured, the AI assistant can use the following tools:

### `samtools_view` - View/Convert SAM/BAM/CRAM

View and convert alignment files, with options for filtering by region, flags, and quality.

**Parameters:**
- `input_file` (required): Path to SAM/BAM/CRAM file.
- `output_format`: Output format (`sam`, `bam`, or `cram`). Default: `bam`.
- `region`: Region to extract (e.g., `chr1:1000-2000`).
- `flags_include`: Include reads with all these flags (integer).
- `flags_exclude`: Exclude reads with any of these flags (integer).
- `quality_min`: Minimum mapping quality (integer).

### `samtools_sort` - Sort SAM/BAM Files

Sort SAM/BAM files by coordinate or read name.

**Parameters:**
- `input_file` (required): Path to SAM/BAM file.
- `sort_by`: Sort order (`coordinate` or `name`). Default: `coordinate`.
- `output_format`: Output format (`sam`, `bam`, or `cram`). Default: `bam`.

### `samtools_index` - Create Index

Create an index for sorted BAM/CRAM files.

**Parameters:**
- `input_file` (required): Path to sorted BAM/CRAM file.
- `index_type`: Index type (`bai` or `csi`). Default: `bai`.

### `samtools_stats` - Generate Alignment Statistics

Generate detailed statistics from an alignment file.

**Parameters:**
- `input_file` (required): Path to BAM file.
- `region`: Region to analyze.
- `reference`: Reference FASTA file (required for CRAM).

### `samtools_flagstat` - Count Reads by Flag

Count reads in each FLAG category, providing a quick summary of alignment status.

**Parameters:**
- `input_file` (required): Path to BAM file.

### `samtools_depth` - Calculate Per-Position Depth

Calculate the per-position read depth across a specified region or the entire file.

**Parameters:**
- `input_file` (required): Path to BAM file.
- `region`: Region to analyze.
- `max_depth`: Maximum depth to report (default: 8000).

## Examples

### Sort a BAM file
```
Sort the alignment.bam file by coordinate and output as a new BAM file.
```

### Get alignment statistics
```
Generate alignment statistics for my_reads.bam.
```

### Index a sorted BAM file
```
Create a BAI index for the sorted_reads.bam file.
```

## Development

### Running tests

```bash
pytest tests/
```

### Building Docker image

```bash
docker build -t bio-mcp-samtools .
```

## License

MIT License
