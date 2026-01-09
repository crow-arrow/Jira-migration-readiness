import typer
from typer.main import get_command

app = typer.Typer(help="Jira Migration Readiness Tool")

@app.command()
def hello():
    """Sanity check command."""
    print("JMRT is alive 🚀")

# IMPORTANT: export a Click command explicitly for console scripts
cli = get_command(app)

if __name__ == "__main__":
    app()
