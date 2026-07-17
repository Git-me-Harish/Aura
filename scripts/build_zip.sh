#!/usr/bin/env bash
# AURA — production-grade zip builder.
#
# Produces /home/z/my-project/download/aura.zip containing a clean, runnable
# project that the user can unzip on their local machine and open in VS Code.
#
# Excludes:
#   - node_modules/          (1.2G — will be reinstalled with bun/npm install)
#   - .next/                  (Next.js build cache)
#   - .git/                   (version history, large)
#   - skills/                 (61M — skill templates, NOT part of AURA)
#   - aura-backend/pgdata/   (Postgres runtime data — recreated on first start)
#   - aura-backend/qdrant_data/  (Qdrant runtime data)
#   - aura-backend/logs/      (runtime logs)
#   - aura-backend/__pycache__/ (Python bytecode)
#   - aura-backend/.venv/     (Python virtualenv, if any)
#   - dev.log, server.log     (runtime logs)
#   - tool-results/           (temp)
#   - db/custom.db            (SQLite runtime DB — recreated by prisma db:push)
#   - worklog.md              (internal agent log)
#   - upload/                 (temp uploads)
#   - .zscripts/              (internal build scripts)
#   - download/               (the output dir itself)
#   - .claude/, .z-ai-config/ (IDE-specific config)
#   - *.log, *.pid            (any log/pid files anywhere)
#   - __pycache__, *.pyc      (Python cache anywhere)

set -e

PROJECT_ROOT=/home/z/my-project
OUTPUT_DIR=/home/z/my-project/download
OUTPUT_FILE=$OUTPUT_DIR/aura.zip
STAGING=/tmp/aura-staging

echo "════════════════════════════════════════════════════════════════"
echo "AURA zip builder"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Clean staging
rm -rf $STAGING
mkdir -p $STAGING

# Clean any previous zip
rm -f $OUTPUT_FILE
mkdir -p $OUTPUT_DIR

# Build the exclusion list (relative patterns)
EXCLUDES=(
  --exclude='node_modules'
  --exclude='.next'
  --exclude='.git'
  --exclude='.gitignore'            # we'll re-add a cleaned one
  --exclude='skills'
  --exclude='aura-backend/pgdata'
  --exclude='aura-backend/qdrant_data'
  --exclude='aura-backend/logs'
  --exclude='aura-backend/.venv'
  --exclude='aura-backend/__pycache__'
  --exclude='aura-backend/.env'      # don't ship real .env (we ship .env.example)
  --exclude='dev.log'
  --exclude='server.log'
  --exclude='tool-results'
  --exclude='db/custom.db'
  --exclude='worklog.md'
  --exclude='upload'
  --exclude='.zscripts'
  --exclude='download'
  --exclude='.claude'
  --exclude='.z-ai-config'
  --exclude='*.log'
  --exclude='*.pid'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='.DS_Store'
  --exclude='.vscode'               # user can create their own
  --exclude='aura.zip'
)

# Copy project into staging (using rsync with excludes for reliability)
rsync -a \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='.git' \
  --exclude='skills' \
  --exclude='aura-backend/pgdata' \
  --exclude='aura-backend/qdrant_data' \
  --exclude='aura-backend/logs' \
  --exclude='aura-backend/.venv' \
  --exclude='aura-backend/__pycache__' \
  --exclude='aura-backend/.env' \
  --exclude='dev.log' \
  --exclude='server.log' \
  --exclude='tool-results' \
  --exclude='db/custom.db' \
  --exclude='worklog.md' \
  --exclude='upload' \
  --exclude='.zscripts' \
  --exclude='download' \
  --exclude='.claude' \
  --exclude='.z-ai-config' \
  --exclude='*.log' \
  --exclude='*.pid' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.vscode' \
  --exclude='aura.zip' \
  --exclude='.env' \
  $PROJECT_ROOT/ $STAGING/aura/

# Make sure the .env.example files are present
echo "Checking .env.example files..."
test -f $STAGING/aura/.env.example && echo "  ✓ frontend .env.example"
test -f $STAGING/aura/aura-backend/.env.example && echo "  ✓ backend .env.example"

# Make sure READMEs are present
test -f $STAGING/aura/README.md && echo "  ✓ root README.md"
test -f $STAGING/aura/SETUP.md && echo "  ✓ SETUP.md"
test -f $STAGING/aura/aura-backend/README.md && echo "  ✓ backend README.md"

# Create empty dirs that the app expects to exist at runtime
mkdir -p $STAGING/aura/aura-backend/logs
mkdir -p $STAGING/aura/aura-backend/pgdata
mkdir -p $STAGING/aura/aura-backend/qdrant_data
mkdir -p $STAGING/aura/db
echo "  ✓ created empty runtime dirs (logs, pgdata, qdrant_data, db)"

# Add .gitkeep files to keep empty dirs in the zip
touch $STAGING/aura/aura-backend/logs/.gitkeep
touch $STAGING/aura/aura-backend/pgdata/.gitkeep
touch $STAGING/aura/aura-backend/qdrant_data/.gitkeep
touch $STAGING/aura/db/.gitkeep

# Show what's about to be zipped
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "Staging tree (top-level):"
echo "════════════════════════════════════════════════════════════════"
ls -la $STAGING/aura/
echo ""
echo "Staging size:"
du -sh $STAGING/aura/
echo ""
echo "Per-directory sizes:"
du -sh $STAGING/aura/* 2>/dev/null | sort -hr
echo ""

# Create the zip
echo "════════════════════════════════════════════════════════════════"
echo "Building zip → $OUTPUT_FILE"
echo "════════════════════════════════════════════════════════════════"
cd $STAGING
zip -r -q $OUTPUT_FILE aura/

# Show result
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "DONE"
echo "════════════════════════════════════════════════════════════════"
ls -lh $OUTPUT_FILE
echo ""
echo "Zip top-level contents:"
unzip -l $OUTPUT_FILE | head -30
echo ""
echo "Total files in zip:"
unzip -l $OUTPUT_FILE | tail -1

# Clean staging
rm -rf $STAGING
