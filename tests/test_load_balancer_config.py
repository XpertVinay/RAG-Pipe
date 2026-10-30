"""Tests for Nginx Load Balancer Configuration, Production Flags, and Verification Utilities."""

import os
import re
import pytest
from app.config import Settings
from scripts.verify_load_balancing import evaluate_distribution


def test_lb_config_settings_defaults():
    """Verify that LB debug headers are OFF by default for production safety."""
    # Check class field default is False
    assert Settings.model_fields["ENABLE_LB_DEBUG_HEADERS"].default is False
    assert Settings.model_fields["LB_ALGORITHM"].default == "round_robin"

    # When created without an env file or in production
    clean_settings = Settings(_env_file=None, ENABLE_LB_DEBUG_HEADERS=False)
    assert clean_settings.ENABLE_LB_DEBUG_HEADERS is False
    assert clean_settings.LB_ALGORITHM == "round_robin"


def test_lb_config_settings_env_override():
    """Verify that ENABLE_LB_DEBUG_HEADERS can be enabled via environment variable / parameter."""
    settings = Settings(_env_file=None, ENABLE_LB_DEBUG_HEADERS=True, LB_ALGORITHM="least_conn")
    assert settings.ENABLE_LB_DEBUG_HEADERS is True
    assert settings.LB_ALGORITHM == "least_conn"


def test_nginx_conf_structure():
    """Validate that nginx.conf has proper upstream log format and flag mappings."""
    nginx_conf_path = os.path.join(
        os.path.dirname(__file__), "..", "nginx", "nginx.conf"
    )
    assert os.path.exists(nginx_conf_path), "nginx.conf must exist"

    with open(nginx_conf_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for upstream log format
    assert "log_format upstream_lb" in content
    assert 'upstream_addr="$upstream_addr"' in content
    assert 'upstream_status="$upstream_status"' in content
    assert 'upstream_time="$upstream_response_time"' in content

    # Check for flag mapping
    assert 'map "${ENABLE_LB_DEBUG_HEADERS}" $env_debug_upstream' in content
    assert 'map $http_x_debug_lb $upstream_debug_addr' in content
    assert 'default "";' in content

    # Check for verification response headers
    assert "add_header X-Served-By $upstream_debug_addr always;" in content
    assert "add_header X-Upstream-Response-Time $upstream_debug_time always;" in content
    assert "add_header X-Upstream-Status $upstream_debug_status always;" in content

    # Check for upstream definition and health check location
    assert "upstream rag_backend {" in content
    assert "server rag-agent:8000" in content
    assert "location /lb-status {" in content


def test_nginx_template_structure():
    """Validate that nginx.conf.template exists and includes substitution markers."""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "nginx", "templates", "nginx.conf.template"
    )
    assert os.path.exists(template_path), "nginx.conf.template must exist"

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "${ENABLE_LB_DEBUG_HEADERS}" in content
    assert "${PROXY_PORT}" in content
    assert "log_format upstream_lb" in content


def test_verify_load_balancing_equal_distribution():
    """Verify evaluate_distribution accurately identifies balanced traffic."""
    counts = {
        "172.20.0.2:8000": 510,
        "172.20.0.3:8000": 490,
    }
    # 51% vs 49% -> drift is 2% -> well within 20% tolerance
    is_balanced = evaluate_distribution(counts, total=1000, tolerance=0.20)
    assert is_balanced is True


def test_verify_load_balancing_skewed_distribution():
    """Verify evaluate_distribution flags skewed traffic."""
    counts = {
        "172.20.0.2:8000": 850,
        "172.20.0.3:8000": 150,
    }
    # 85% vs 15% -> drift is 70% -> exceeds 20% tolerance
    is_balanced = evaluate_distribution(counts, total=1000, tolerance=0.20)
    assert is_balanced is False


def test_verify_load_balancing_single_backend():
    """Verify single instance detection does not report a false skew failure."""
    counts = {
        "172.20.0.2:8000": 100,
    }
    is_balanced = evaluate_distribution(counts, total=100, tolerance=0.20)
    assert is_balanced is True
