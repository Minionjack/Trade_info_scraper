#!/bin/bash

echo "🔄 Activating virtual environment..."
source venv/bin/activate

echo "🚀 Running scraper..."
python Image_and_text_scraper.py

echo "✅ Done. Deactivating..."
deactivate

echo "👋 Goodbye!"