"""
Pytest configuration and shared fixtures
"""
import pytest
import os
import tempfile
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """Create application for testing"""
    # Use test configuration
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['TESTING'] = 'true'
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    return app


@pytest.fixture(scope='function')
def db(app):
    """Create database for testing"""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app, db):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
