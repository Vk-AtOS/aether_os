import os

def test_migrate_script_exists():
    assert os.path.exists("scripts/migrate_db.py")

def test_demo_trigger_exists():
    assert os.path.exists("scripts/demo_trigger.sh")

def test_start_demo_exists():
    assert os.path.exists("scripts/start_demo.sh")

def test_env_example_exists():
    assert os.path.exists(".env.example")

def test_readme_exists():
    assert os.path.exists("README.md")
