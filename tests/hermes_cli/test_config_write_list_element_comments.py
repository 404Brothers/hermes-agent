"""Round-trip config writes must not destroy semantically unchanged nodes.

Measured 2026-09-16 on a real config: ``atomic_roundtrip_yaml_save._merge``
recursed only into dicts; any non-dict value — including lists — was assigned
wholesale (`dst[key] = value`), which replaced the ruamel ``CommentedSeq`` and
with it every comment anchored inside a list element's mapping
(``hooks.pre_llm_call[1].ca._items['timeout']``). A v44→v45 migration changed
nothing but ``_config_version`` and still dropped the comment.

Reconstruction note (2026-09-20, issue #95): this file re-establishes the
carry-candidate contract lost with a disposable staging worktree. The fix
shape is the one documented on upstream PR #105271: a semantically equal
existing ruamel node is kept untouched (with a YAML 1.1 quoting exception),
type-strict comparison (``True != 1``, ``1.0 != 1``, subclass-aware numerics)
and a 4096-col round-trip emitter so long plain scalars are not re-folded.
"""

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import hermes_yaml as yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

AMBIENT_COMMENT = "rationale anchored inside a list element"
HEADER_COMMENT = "top-of-file rationale"

# Full state on disk: a list element whose mapping carries an anchored comment,
# plus a scalar to type-check. Written as raw text so the comments are real.
LIST_ELEMENT_CONFIG = """\
{header}
_config_version: 44
hooks:
  pre_llm_call:
    - command: first.sh
      timeout: 5
    - command: second.sh
      # {ambient}
      timeout: 20
platform_toolsets:
  cli:
    - file
    - web
""".format(header="# " + HEADER_COMMENT, ambient=AMBIENT_COMMENT)


def _write_config(tmp_path, text):
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")


def _load_save(tmp_path, mutate=None):
    """``load_config`` → optional mutation → ``save_config`` under *tmp_path* home."""
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        if mutate is not None:
            mutate(cfg)
        save_config(cfg)


def _run_ladder(tmp_path, current_ver=44):
    from hermes_cli.config_migrations import run_migrations

    results = {"env_added": [], "config_added": [], "warnings": []}
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        run_migrations(current_ver, results, quiet=True)
    return results


def _no_trailing_whitespace(text):
    assert not re.search(r"[ \t]+$", text, re.M), "emitter re-folded lines with trailing whitespace"


class TestProvenance:
    def test_roundtrip_writers_import_from_this_tree(self):
        # The write path must be exercised against THIS tree, not an installed
        # copy: a stale editable install would make every assertion here lie.
        import hermes_cli.config as cli_config
        import utils

        for module in (cli_config, utils):
            module_root = str(Path(module.__file__).resolve())
            assert module_root.startswith(str(REPO_ROOT)), module_root


class TestUnchangedListElementComments:
    def test_comment_in_unchanged_list_element_survives_save(self, tmp_path):
        _write_config(tmp_path, LIST_ELEMENT_CONFIG)
        _load_save(tmp_path)  # save without changes: pure round-trip

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert AMBIENT_COMMENT in written

    def test_comment_in_unchanged_list_element_survives_migration(self, tmp_path, capsys):
        _write_config(tmp_path, LIST_ELEMENT_CONFIG)
        with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
            from hermes_cli.config import migrate_config

            migrate_config(interactive=False)
            capsys.readouterr()  # swallow migration console noise

        raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert raw["_config_version"] >= 45
        assert "connections" in raw["platform_toolsets"]["cli"]
        assert AMBIENT_COMMENT in written

    def test_unchanged_float_in_list_element_keeps_node(self, tmp_path):
        # ruamel wraps every float in ScalarFloat (a float subclass) while the
        # incoming PyYAML value is a plain float: type-identity comparison would
        # misread the unchanged 0.7 as changed and swap the containing list node.
        text = (
            "config:\n"
            "  sample:\n"
            "    - name: block\n"
            "      # anchor comment\n"
            "      temperature: 0.7\n"
        )
        _write_config(tmp_path, text)
        _load_save(tmp_path)

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert yaml.safe_load(written)["config"]["sample"][0]["temperature"] == 0.7
        assert "anchor comment" in written


class TestDeletionSemantics:
    def test_intentional_key_deletion_still_lands(self, tmp_path):
        _write_config(tmp_path, LIST_ELEMENT_CONFIG)

        def remove_key(cfg):
            cfg.pop("platform_toolsets")

        _load_save(tmp_path, remove_key)

        raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "platform_toolsets" not in raw
        # Deletion works — and must not cost the untouched section's comments.
        assert AMBIENT_COMMENT in written

    def test_changed_list_still_updates(self, tmp_path):
        _write_config(tmp_path, LIST_ELEMENT_CONFIG)

        def bump_timeout(cfg):
            cfg["hooks"]["pre_llm_call"][0]["timeout"] = 60

        _load_save(tmp_path, bump_timeout)

        raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert raw["hooks"]["pre_llm_call"][0]["timeout"] == 60


class TestTypeStrictness:
    """The equality guard must not skip genuine scalar type changes."""

    @pytest.mark.parametrize("original,new_value", [(True, 1), (1, True), (1, 1.0), (1.0, 1)])
    def test_scalar_type_change_is_not_skipped(self, tmp_path, original, new_value):
        text = "tuning:\n  flag: {}\n".format(
            "true" if original is True else "false" if original is False else repr(original)
        )
        _write_config(tmp_path, text)
        _load_save(tmp_path, lambda cfg: cfg["tuning"].update(flag=new_value))

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        raw = yaml.safe_load(written)
        assert raw["tuning"]["flag"] == new_value
        assert type(raw["tuning"]["flag"]) is type(new_value)


class TestYaml11Quoting:
    @pytest.mark.parametrize("word", ["off", "on", "yes", "no"])
    def test_unquoted_ambiguous_strings_are_rewritten_quoted(self, tmp_path, word):
        _write_config(tmp_path, "approvals:\n  mode: {}\n".format(word))
        _load_save(
            tmp_path,
            lambda cfg: cfg.update(approvals={"mode": word}),  # incoming plain str
        )

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        raw = yaml.safe_load(written)
        assert isinstance(raw["approvals"]["mode"], str), written
        assert raw["approvals"]["mode"] == word
        assert '"{}"'.format(word) in written or "'{}'".format(word) in written

    def test_already_quoted_ambiguous_string_survives_unchanged(self, tmp_path):
        _write_config(tmp_path, 'approvals:\n  mode: "off"\n')
        _load_save(
            tmp_path,
            lambda cfg: cfg.update(approvals={"mode": "off"}),
        )

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert '"off"' in written  # no churn: already-quoted stays as-is
        assert isinstance(yaml.safe_load(written)["approvals"]["mode"], str)

    def test_unchanged_plain_scalar_representation_survives(self, tmp_path):
        text = "model: test/original\n"
        _write_config(tmp_path, text)
        _load_save(tmp_path)

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert yaml.safe_load(written)["model"] == "test/original"
        assert "test/original" in written


class TestReflow:
    def test_long_scalar_not_reflowed(self, tmp_path):
        long_scalar = (
            "You are Hermes Agent, built by Nous Research. Be direct: match the "
            "length of the question, answer in the user's language, and never "
            "claim to have checked something you did not check."
        )
        _write_config(tmp_path, 'personality:\n  direct: "{}"\n'.format(long_scalar))
        _load_save(tmp_path)

        written = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        # The emitter must not re-fold the long plain scalar at width 80 and
        # leave a trailing space in every fold (E1 secondary finding).
        assert not re.search(r"[ \t]+$", written, re.M)
        assert yaml.safe_load(written)["personality"]["direct"] == long_scalar
        assert any(len(line) > 100 for line in written.splitlines()), written
