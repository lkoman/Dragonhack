# Rostra

## How to run
### Naredi venv (ce zelis, priporocam) nujno potreben Python 3.12
```
python -m venv venv 
venv\Scripts\activate
```
### V primeru, da imaš več verzij
```
py -3.12 -m venv venv 
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
