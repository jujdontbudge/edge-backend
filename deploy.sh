#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Edge Backend Deployment ==="
echo ""

# Check Railway login
if ! railway whoami 2>/dev/null; then
    echo "ERROR: Not logged into Railway. Run: railway login"
    exit 1
fi

echo "Logged in as: $(railway whoami 2>&1)"
echo ""

# Check if project exists
if railway status 2>/dev/null | grep -q "Project"; then
    echo "Railway project already linked."
else
    echo "Creating new Railway project..."
    railway init --name "edge-backend"
fi

echo ""
echo "Deploying backend..."
railway up --detach

echo ""
echo "Waiting for deployment..."
sleep 10

# Get the public URL
DOMAIN=$(railway domain 2>/dev/null || echo "")
if [ -z "$DOMAIN" ]; then
    echo "Generating public domain..."
    railway domain
    DOMAIN=$(railway domain 2>/dev/null)
fi

echo ""
echo "=== Deployment Complete ==="
echo "Backend URL: https://$DOMAIN"
echo ""
echo "Next steps:"
echo "  1. Set environment variables:"
echo "     railway vars set SUPABASE_URL=https://ibdjpqmqnavioukxjpun.supabase.co"
echo "     railway vars set SUPABASE_ANON_KEY=<your-key>"
echo "     railway vars set OPENROUTER_API_KEY=<your-key>"
echo "     railway vars set CORS_ORIGINS=*"
echo ""
echo "  2. Update iOS app Secrets.plist:"
echo "     BACKEND_URL = https://$DOMAIN"
echo ""
echo "  3. Test: curl https://$DOMAIN/docs"
