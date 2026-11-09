"""Instância única de SQLAlchemy compartilhada por modelos, serviços e rotas."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
