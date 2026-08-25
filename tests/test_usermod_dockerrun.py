from cibuildmp.usermod import dockerrun


def test_no_override_and_no_registration_means_host_build(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for_port("unix") is None


def test_registered_default_is_used_when_no_env_override(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun, "PORT_IMAGES", {"unix": "ghcr.io/example/cibuildmp-unix:latest"}
    )
    assert dockerrun.image_for_port("unix") == "ghcr.io/example/cibuildmp-unix:latest"


def test_env_override_wins_over_registered_default(monkeypatch):
    monkeypatch.setenv("CIBMP_UNIX_DOCKER_IMAGE", "cibuildmp-unix:local")
    monkeypatch.setattr(
        dockerrun, "PORT_IMAGES", {"unix": "ghcr.io/example/cibuildmp-unix:latest"}
    )
    assert dockerrun.image_for_port("unix") == "cibuildmp-unix:local"


def test_unregistered_port_with_no_override_is_host_build(monkeypatch):
    monkeypatch.delenv("CIBMP_WINDOWS_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for_port("windows") is None
