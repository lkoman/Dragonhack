# Rostra

Rostra is a multimodal AI web application for live lectures. It
processes speech, text, and visual input in real time to provide
transcription, slide OCR, engagement analysis, and AI-generated
summaries. It also builds a searchable archive of lecture content for
later review.

## Requirements

-   Python 3.12
-   (Recommended) virtual environment

## Setup

### 1. Create and activate virtual environment

``` bash
python -m venv venv
venv\Scripts\activate
```

If multiple Python versions are installed:

``` bash
py -3.12 -m venv venv
(or python3.12 -m venv venv)
venv\Scripts\activate
```

### 2. Install dependencies

``` bash
pip install -r requirements.txt
```

### 3. Configure API key

Create a `.env` file inside the `backend/` directory:

    backend/.env

Add:

    OPENAI_API_KEY=your_api_key_here

### 4. Run backend

``` bash
cd backend
uvicorn main:app --reload --port 8000
```

### 5. Run frontend

Option 1: - Open `frontend/menu.html` in browser

Option 2: - Use VSCode Live Server - Right click `menu.html` - Open with
Live Server

## Notes

-   Backend runs on http://localhost:8000
-   Ensure backend is running before using frontend
