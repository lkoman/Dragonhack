# tvoja mami

## How to run
### Naredi venv (ce zelis, priporocam)
```
python -m venv venv 
venv\Scripts\activate
```
### Install requirements
```
pip install -r requirements.txt
```

### Dodaj api key
```
naredi mapo .env v folderju backend
dodaj not line:
OPENAI_API_KEY=sk-.........kljuc
```

### Zalaufi backend
```
cd backend
uvicorn main:app --reload --port 8000
```

### Zalaufi frontend
```
desn klik na index.html -> Open with live server
```