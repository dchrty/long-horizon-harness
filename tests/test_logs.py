"""Unit tests for the multiplexed logs view (snapshot path only).

Follow mode spawns threads + Popen.poll loops; not worth the complexity
to mock cleanly. The snapshot path covers the interesting formatting
logic (prefix + colour cycle + merge of stdout/stderr).
"""

from unittest.mock import patch

from agent_factory import config, logs


def test_show_reports_no_agents_when_empty(project_dir, capsys):
    layout = config.discover(project_dir)
    with patch("agent_factory.logs.list_running", return_value=[]):
        logs.show(layout, follow=False, tail=10)
    out = capsys.readouterr().out
    assert "No running agents" in out


def test_show_snapshot_prints_each_agent_with_prefix(project_dir, capsys):
    layout = config.discover(project_dir)
    agents = [f"{layout.run_prefix}-1", f"{layout.run_prefix}-2"]
    # Each docker logs call returns different content so we can verify
    # both agents are processed and prefixes are correct.
    call_outputs = {
        agents[0]: "line-a1\nline-a2\n",
        agents[1]: "line-b1\nline-b2-err\n",  # already merged stdout+stderr
    }

    def fake_read(name, tail):
        return call_outputs[name]

    with (
        patch("agent_factory.logs.list_running", return_value=agents),
        patch("agent_factory.logs.read_container_logs", side_effect=fake_read),
    ):
        logs.show(layout, follow=False, tail=10)
    out = capsys.readouterr().out
    # Both agents' lines should appear, prefixed with their container name.
    assert agents[0] in out
    assert agents[1] in out
    assert "line-a1" in out
    assert "line-a2" in out
    assert "line-b1" in out
    # stderr content (merged by read_container_logs) is in the stream
    assert "line-b2-err" in out


def test_show_filters_to_single_agent(project_dir, capsys):
    layout = config.discover(project_dir)
    agents = [f"{layout.run_prefix}-1", f"{layout.run_prefix}-2"]
    captured_cmds: list[list[str]] = []

    def fake_read(name, tail):
        captured_cmds.append(name)
        return "x\n"

    with (
        patch("agent_factory.logs.list_running", return_value=agents),
        patch("agent_factory.logs.read_container_logs", side_effect=fake_read),
    ):
        logs.show(layout, follow=False, tail=10, agent_filter=agents[1])

    # docker logs should only be invoked for agent #2, not agent #1.
    assert captured_cmds == [agents[1]]


def test_show_reports_when_filter_misses(project_dir, capsys):
    layout = config.discover(project_dir)
    agents = [f"{layout.run_prefix}-1"]
    with (
        patch("agent_factory.logs.list_running", return_value=agents),
        patch("agent_factory.logs.read_container_logs") as rcl,
    ):
        logs.show(layout, follow=False, tail=10, agent_filter="not-a-real-agent")
    out = capsys.readouterr().out
    assert "No running agent named" in out
    # And we should NOT have invoked docker logs at all.
    rcl.assert_not_called()


def test_show_handles_empty_output(project_dir, capsys):
    """An agent that's freshly-started may have no output yet; we render
    a placeholder rather than a confusing blank prefix."""
    layout = config.discover(project_dir)
    agents = [f"{layout.run_prefix}-1"]
    with (
        patch("agent_factory.logs.list_running", return_value=agents),
        patch("agent_factory.logs.read_container_logs", return_value=""),
    ):
        logs.show(layout, follow=False, tail=10)
    out = capsys.readouterr().out
    assert "no output yet" in out


def test_show_wait_polls_until_agents_appear(project_dir, capsys):
    """wait=True should poll list_running until it returns a non-empty
    list, then proceed to snapshot/follow as normal."""
    layout = config.discover(project_dir)
    agents = [f"{layout.run_prefix}-1"]
    # First two calls return empty (no agents yet); third returns the agent.
    side_effects = [[], [], agents]
    with (
        patch("agent_factory.logs.list_running", side_effect=side_effects) as lr,
        patch("agent_factory.logs.read_container_logs", return_value="hello\n"),
        patch("agent_factory.logs.time.sleep"),  # don't actually sleep in tests
    ):
        logs.show(layout, follow=False, tail=10, wait=True)
    out = capsys.readouterr().out
    assert "Polling every" in out
    assert "Found 1 agent(s)" in out
    assert "hello" in out
    # list_running called at least 3 times: initial check + 2 polls.
    assert lr.call_count >= 3


def test_show_wait_returns_quietly_on_keyboard_interrupt(project_dir, capsys):
    """If the user Ctrl-Cs during the wait, exit cleanly without traceback."""
    layout = config.discover(project_dir)

    def raise_interrupt(*_, **__):
        raise KeyboardInterrupt()

    with (
        patch("agent_factory.logs.list_running", return_value=[]),
        patch("agent_factory.logs.time.sleep", side_effect=raise_interrupt),
    ):
        logs.show(layout, follow=False, tail=10, wait=True)
    out = capsys.readouterr().out
    assert "Stopping wait" in out


def test_show_without_wait_exits_when_no_agents(project_dir, capsys):
    """Default behaviour preserved: no agents + wait=False prints once and exits."""
    layout = config.discover(project_dir)
    with patch("agent_factory.logs.list_running", return_value=[]):
        logs.show(layout, follow=False, tail=10, wait=False)
    out = capsys.readouterr().out
    assert "No running agents" in out
    # The polling banner must NOT appear when wait=False.
    assert "Polling every" not in out
