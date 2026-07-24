"""Tests for _resolve_mentions, _resolve_channels, and auto-resolution in post/send."""

from unittest.mock import AsyncMock, patch

import pytest

import slack_mcp_server as sms


class TestResolveMentions:
    @pytest.mark.asyncio
    async def test_resolves_simple_handle(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = [{"id": "U12345", "handle": "jdoe"}]
            result = await sms._resolve_mentions("Hey @jdoe check this")
            assert result == "Hey <@U12345> check this"
            mock_resolve.assert_called_once_with("jdoe")

    @pytest.mark.asyncio
    async def test_resolves_dotted_handle(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = [{"id": "U99999", "handle": "john.doe"}]
            result = await sms._resolve_mentions("cc @john.doe")
            assert result == "cc <@U99999>"

    @pytest.mark.asyncio
    async def test_resolves_hyphenated_handle(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = [{"id": "UABC", "handle": "jane-smith"}]
            result = await sms._resolve_mentions("ping @jane-smith")
            assert result == "ping <@UABC>"

    @pytest.mark.asyncio
    async def test_skips_already_formatted_mention(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            result = await sms._resolve_mentions("Hey <@U12345> check this")
            assert result == "Hey <@U12345> check this"
            mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_leaves_unresolved_mention_unchanged(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = []
            result = await sms._resolve_mentions("Hey @nonexistent")
            assert result == "Hey @nonexistent"

    @pytest.mark.asyncio
    async def test_no_mentions_returns_unchanged(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            result = await sms._resolve_mentions("No mentions here")
            assert result == "No mentions here"
            mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicates_lookups(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = [{"id": "U11111", "handle": "alice"}]
            result = await sms._resolve_mentions("@alice said hi to @alice")
            assert result == "<@U11111> said hi to <@U11111>"
            mock_resolve.assert_called_once_with("alice")

    @pytest.mark.asyncio
    async def test_multiple_different_mentions(self):
        with patch.object(sms, "resolve_user_id", new_callable=AsyncMock) as mock_resolve:
            async def side_effect(query):
                users = {"alice": [{"id": "UA"}], "bob": [{"id": "UB"}]}
                return users.get(query, [])

            mock_resolve.side_effect = side_effect
            result = await sms._resolve_mentions("@alice and @bob")
            assert "<@UA>" in result
            assert "<@UB>" in result
            assert "@alice" not in result
            assert "@bob" not in result

    @pytest.mark.asyncio
    async def test_empty_string(self):
        result = await sms._resolve_mentions("")
        assert result == ""


class TestResolveChannels:
    @pytest.mark.asyncio
    async def test_resolves_channel_name(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            mock_ch.return_value = "C12345"
            result = await sms._resolve_channels("post in #general")
            assert result == "post in <#C12345>"
            mock_ch.assert_called_once_with("general")

    @pytest.mark.asyncio
    async def test_resolves_hyphenated_channel(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            mock_ch.return_value = "CABC"
            result = await sms._resolve_channels("see #my-channel")
            assert result == "see <#CABC>"

    @pytest.mark.asyncio
    async def test_skips_already_formatted_channel(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            result = await sms._resolve_channels("see <#C12345>")
            assert result == "see <#C12345>"
            mock_ch.assert_not_called()

    @pytest.mark.asyncio
    async def test_leaves_unresolved_channel_unchanged(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            mock_ch.return_value = ""
            result = await sms._resolve_channels("see #nonexistent")
            assert result == "see #nonexistent"

    @pytest.mark.asyncio
    async def test_no_channels_returns_unchanged(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            result = await sms._resolve_channels("No channels here")
            assert result == "No channels here"
            mock_ch.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicates_lookups(self):
        with patch.object(sms, "get_channel_id_by_name", new_callable=AsyncMock) as mock_ch:
            mock_ch.return_value = "C999"
            result = await sms._resolve_channels("#dev and also #dev")
            assert result == "<#C999> and also <#C999>"
            mock_ch.assert_called_once_with("dev")

    @pytest.mark.asyncio
    async def test_empty_string(self):
        result = await sms._resolve_channels("")
        assert result == ""


class TestPostMessageResolveReferences:
    @pytest.mark.asyncio
    async def test_resolves_by_default(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True}

        with (
            patch.object(sms, "_resolve_mentions", new_callable=AsyncMock, return_value="resolved mentions") as mock_m,
            patch.object(sms, "_resolve_channels", new_callable=AsyncMock, return_value="resolved all") as mock_c,
            patch.object(sms, "join_channel", new_callable=AsyncMock),
        ):
            await sms.post_message("C123", "@alice in #general", skip_log=True)
            mock_m.assert_called_once_with("@alice in #general")
            mock_c.assert_called_once_with("resolved mentions")

    @pytest.mark.asyncio
    async def test_skips_resolution_when_disabled(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True}

        with (
            patch.object(sms, "_resolve_mentions", new_callable=AsyncMock) as mock_m,
            patch.object(sms, "_resolve_channels", new_callable=AsyncMock) as mock_c,
            patch.object(sms, "join_channel", new_callable=AsyncMock),
        ):
            await sms.post_message("C123", "<@U123> in <#C456>", skip_log=True, resolve_references=False)
            mock_m.assert_not_called()
            mock_c.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolved_text_is_sent(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True}

        with (
            patch.object(sms, "_resolve_mentions", new_callable=AsyncMock, return_value="<@U123> says hi"),
            patch.object(sms, "_resolve_channels", new_callable=AsyncMock, return_value="<@U123> says hi in <#C456>"),
            patch.object(sms, "join_channel", new_callable=AsyncMock),
        ):
            await sms.post_message("C789", "@alice says hi in #general", skip_log=True)
            call_payload = mock_make_request.call_args
            assert call_payload[1]["payload"]["text"] == "<@U123> says hi in <#C456>"


class TestSendDmResolveReferences:
    @pytest.mark.asyncio
    async def test_passes_resolve_references_through(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True, "channel": {"id": "D999"}}

        with patch.object(sms, "post_message", new_callable=AsyncMock, return_value=True) as mock_pm:
            await sms.send_dm("U123", "hey @alice", resolve_references=False)
            mock_pm.assert_called_once()
            assert mock_pm.call_args[1]["resolve_references"] is False

    @pytest.mark.asyncio
    async def test_defaults_to_resolve_true(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True, "channel": {"id": "D999"}}

        with patch.object(sms, "post_message", new_callable=AsyncMock, return_value=True) as mock_pm:
            await sms.send_dm("U123", "hey @alice")
            assert mock_pm.call_args[1]["resolve_references"] is True


class TestSendGroupDmResolveReferences:
    @pytest.mark.asyncio
    async def test_passes_resolve_references_through(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True, "channel": {"id": "G999"}}

        with patch.object(sms, "post_message", new_callable=AsyncMock, return_value=True) as mock_pm:
            await sms.send_group_dm(["U1", "U2"], "hey @bob", resolve_references=False)
            mock_pm.assert_called_once()
            assert mock_pm.call_args[1]["resolve_references"] is False

    @pytest.mark.asyncio
    async def test_defaults_to_resolve_true(self, mock_make_request, mock_log_to_slack):
        mock_make_request.return_value = {"ok": True, "channel": {"id": "G999"}}

        with patch.object(sms, "post_message", new_callable=AsyncMock, return_value=True) as mock_pm:
            await sms.send_group_dm(["U1", "U2"], "hey @bob")
            assert mock_pm.call_args[1]["resolve_references"] is True
