"""Ponto de entrada para desenvolvimento: `python run.py`."""

from exatamed import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
