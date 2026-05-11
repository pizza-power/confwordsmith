# confwordsmith

Enterprise password wordlist generator that extracts organizational terminology from Atlassian Confluence for authorized internal security testing and hash cracking operations.

**confwordsmith does NOT perform password attacks or cracking.** It generates candidate wordlists and Hashcat rule files only.

---

## Features!!!!!

- **Confluence Cloud and Server/Data Center** support via REST APIs
- **Incremental sync** -- only fetch changed pages on subsequent runs
- **Multithreaded** page retrieval with rate limiting and retries
- **Smart tokenization** -- preserves CamelCase, ALLCAPS acronyms, mixed-case enterprise terms
- **Noise filtering** -- removes UUIDs, hashes, base64 blobs, URLs, minified JS, binary junk
- **Common word filtering** -- case-insensitive removal of common English words via configurable word list
- **Weighted scoring** -- ranks candidates by title presence, frequency, multi-space usage, recency
- **Dictionary comparison** -- optionally diff against rockyou, SecLists, or custom wordlists
- **Mutation engine** -- generates year/symbol/numeric suffixes with aggressive/balanced/minimal profiles
- **Hashcat rule generation** -- enterprise-pattern-aware `.rule` files
- **PRINCE wordlist** output for combinatorial attacks
- **SQLite caching** for page metadata, tokens, and scores
- **Credential scanner** -- detects plaintext passwords, API keys, tokens, and connection strings in page content
- **Configurable** via YAML config file and CLI flags

## Installation

```bash
git clone https://github.com/pizza-power/confwordsmith confwordsmith
cd confwordsmith
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10+.

## Quick Start

```bash
# Basic usage with Confluence Cloud (untested)
python main.py \
  --url https://yourcompany.atlassian.net \
  --token YOUR_API_TOKEN \
  --spaces ENG,IT,HR \
  --output ./output

# Incremental run (only fetch changed pages) (untested)
python main.py \
  --url https://yourcompany.atlassian.net \
  --token YOUR_API_TOKEN \
  --incremental

# Aggressive mutations with dictionary comparison
python main.py \
  --url https://confluence.internal.corp \
  --token YOUR_PAT \
  --mutations aggressive \
  --dictionary /usr/share/wordlists/rockyou.txt \
  --verbose

# Confluence Server/Data Center with proxy
python main.py \
  --url https://confluence.internal.corp \
  --token YOUR_PAT \
  --proxy http://127.0.0.1:8080 \
  --no-verify-ssl \
  --threads 8
```

## CLI Reference

| Flag | Description | Default |
|------|-------------|---------|
| `--url` | Confluence base URL | config.yaml |
| `--token` | PAT or API token | config.yaml |
| `--spaces` | Comma-separated space keys | all spaces |
| `--output` | Output directory | `./output` |
| `--config` | Path to YAML config | `./config.yaml` |
| `--incremental` | Only fetch updated pages | off |
| `--mutations` | Profile: aggressive/balanced/minimal | balanced |
| `--min-length` | Minimum token length | 3 |
| `--threads` | Concurrent page fetch threads | 4 |
| `--proxy` | HTTP/S proxy URL | none |
| `--verify-ssl` | Verify SSL certificates | true |
| `--no-verify-ssl` | Disable SSL verification | - |
| `--exclude-regex` | Regex patterns to exclude | none |
| `--dictionary` | Dictionary file paths | none |
| `--max-spaces` | Limit number of spaces to process | 0 (unlimited) |
| `--cache-db` | SQLite database path | `./cache/confwordsmith.db` |
| `--verbose` / `-v` | Debug logging | off |

## Configuration

Edit `config.yaml` to customize behavior. CLI flags override config values.

### Key sections:

**Confluence connection:**
```yaml
confluence:
  url: "https://confluence.example.com"
  token: "your-pat-here"
  auth_type: "bearer"   # bearer or basic
  verify_ssl: true
  threads: 4
  max_pages: 0           # 0 = unlimited
```

**Space filtering:**
```yaml
spaces:
  include: [ENG, IT, HR]   # empty = all spaces
  exclude: [ARCHIVE]
  max_spaces: 0            # 0 = unlimited; set to N to cap space count
```

**Token filtering:**
```yaml
filters:
  min_length: 3
  max_length: 64
  preserve_acronyms: true
  common_words_file: "./common-words.txt"  # case-insensitive; empty = disabled
  exclude_regex:
    - "^test_.*"
```

**Mutation profiles:**
```yaml
mutations:
  profile: "balanced"    # aggressive | balanced | minimal
  years: [2024, 2025, 2026]
  use_current_year: true
```

**Dictionary comparison:**
```yaml
dictionary:
  paths:
    - /usr/share/wordlists/rockyou.txt
    - /opt/SecLists/Passwords/Common-Credentials/10k-most-common.txt
  mode: "tag"            # remove | tag | preserve
```

**Credential scanning:**
```yaml
credential_scan:
  enabled: true          # scan for plaintext passwords, keys, tokens
```

## Output Files

| File | Description |
|------|-------------|
| `raw_corpus.txt` | All unique tokens, scored and sorted |
| `cleaned_candidates.txt` | Tokens with positive scores |
| `high_confidence.txt` | Top-scoring enterprise-specific candidates |
| `mutations.txt` | Mutated password candidates (year/symbol/number suffixes) |
| `hashcat_rules.rule` | Hashcat-compatible rules for enterprise patterns |
| `prince_input.txt` | Short high-value tokens for PRINCE combinatorial attacks |
| `found_credentials.txt` | Potential plaintext credentials with context and confidence |
| `found_credential_values.txt` | Just the raw credential values (one per line) |
| `statistics.json` | Run statistics, top tokens, score distributions |

### Sample `statistics.json`

```json
{
  "total_tokens": 4823,
  "high_confidence_count": 312,
  "acronym_count": 87,
  "camelcase_count": 156,
  "dictionary_matches": 1204,
  "score_max": 14.5,
  "score_mean": 2.31,
  "output_files": {
    "raw_corpus": 4823,
    "mutations": 28940
  },
  "top_tokens": [
    {"token": "PhoenixMigration", "score": 14.5, "frequency": 23},
    {"token": "TitanOps", "score": 12.2, "frequency": 18}
  ]
}
```

## How Scoring Works

Tokens are scored based on:

| Factor | Weight | Description |
|--------|--------|-------------|
| Title presence | 3.0 | Appears in a page title |
| Heading presence | 2.5 | Appears in H1-H6 headings |
| Frequency | 1.5 | Normalized occurrence count |
| Multi-space | 2.0 | Appears across multiple spaces |
| CamelCase | 1.5 | CamelCase naming pattern |
| ALLCAPS acronym | 2.0 | Enterprise acronym pattern |
| Alphanumeric mix | 1.2 | Contains both letters and digits |
| Length 6-16 | +0.5 | Optimal password root length |

Penalties applied for: dictionary matches (0.3x), very short tokens (0.5x), very long tokens (0.8x), high entropy/randomness (0.7x).

## How Tokenization Works

Input: `PhoenixMigrationQ4`

Output tokens:
- `PhoenixMigrationQ4` (original)
- `Phoenix` (CamelCase split)
- `Migration` (CamelCase split)
- `Q4` (CamelCase split)
- `PhoenixMigration` (adjacent pair)

Input: `HRIS-Portal`

Output tokens:
- `HRIS-Portal` (original)
- `HRISPortal` (joined)
- `HRIS` (acronym, preserved)
- `Portal` (split)

Enterprise acronyms (IAM, HRIS, SCCM, VDI, JKJM, etc.) are always preserved regardless of length.

## Performance Considerations

- **Threading**: Increase `--threads` for faster retrieval on high-bandwidth connections (watch rate limits)
- **Incremental mode**: Use `--incremental` for repeated runs -- only fetches changed pages
- **Max pages**: Set `max_pages` in config to cap retrieval during initial testing
- **SQLite WAL mode**: Enabled by default for concurrent read/write performance
- **Max spaces**: Use `--max-spaces N` to limit how many spaces are processed (useful for quick test runs)
- **Large instances**: For 10k+ pages, consider space-by-space runs with `--spaces`
- **Memory**: Token deduplication is handled in SQLite, keeping memory usage bounded

## Project Structure

```
confwordsmith/
├── main.py              # CLI entry point and orchestration
├── config.yaml          # Default configuration
├── common-words.txt     # Common English words for filtering
├── requirements.txt     # Python dependencies
├── modules/
│   ├── confluence.py    # Confluence REST API client
│   ├── extractor.py     # HTML parsing and content extraction
│   ├── tokenizer.py     # CamelCase/snake_case/acronym splitting
│   ├── filters.py       # Noise removal and acronym preservation
│   ├── scorer.py        # Weighted token scoring engine
│   ├── mutations.py     # Password candidate mutation generator
│   ├── rules.py         # Hashcat rule file generation
│   ├── credscanner.py   # Plaintext credential detection
│   ├── outputs.py       # Output file generation
│   ├── storage.py       # SQLite caching and metadata
│   └── utils.py         # Config loading, logging, helpers
├── output/              # Generated wordlists and rules
├── cache/               # SQLite database
└── logs/                # Application logs
```

