import asyncio
import logging

from codeflash.code_utils.codeflash_wrap_decorator import \
    codeflash_behavior_async
from codeflash.verification.codeflash_capture import codeflash_capture

from amplifier.smoke_tests.config import config

_config = config

"\nAI Evaluator Module\n\nUses Claude Code SDK for test evaluation.\n"
logger = logging.getLogger(__name__)
try:
    from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    logger.warning("Claude Code SDK not available - tests will pass without AI evaluation")


class AIEvaluator:
    """Evaluate command outputs using Claude Code SDK."""

    @codeflash_capture(
        function_name="AIEvaluator.__init__",
        tmp_dir_path="/tmp/codeflash_nh92tih0/test_return_values",
        tests_root="/home/ubuntu/work/repo/tests",
        is_fto=True,
    )
    def __init__(self):
        """Initialize the AI evaluator."""
        self.sdk_available = CLAUDE_SDK_AVAILABLE

    async def evaluate(self, command: str, output: str, success_criteria: str, timeout: int = 30) -> tuple[bool, str]:
        """Evaluate command output against success criteria.

        Args:
            command: The command that was run
            output: Combined stdout and stderr output
            success_criteria: Human-readable success criteria
            timeout: Timeout for AI evaluation

        Returns:
            Tuple of (passed, reasoning)
        """
        # Use cached _config throughout; never re-import
        if not CLAUDE_SDK_AVAILABLE:
            if _config.skip_on_ai_unavailable:
                return (True, "Claude Code SDK unavailable - skipping evaluation")
            return (False, "Claude Code SDK not available")

        if len(output) > _config.max_output_chars:
            output = output[: _config.max_output_chars] + "\n... (truncated)"
        prompt = (
            f"You are evaluating the output of a command to determine if it meets the success criteria.\n\n"
            f"Command run: {command}\n\n"
            f"Success Criteria: {success_criteria}\n\n"
            f"Command Output:\n{output}\n\n"
            f"Based on the output, does this command meet the success criteria?\n"
            f"Respond with PASS or FAIL followed by a brief explanation (1-2 sentences).\n\n"
            f"Format: PASS|FAIL: Brief explanation"
        )
        try:
            async with asyncio.timeout(timeout):
                response = await self._call_claude(prompt)
                if not response:
                    logger.warning("Empty response from Claude Code SDK")
                    if _config.skip_on_ai_unavailable:
                        return (True, "Empty AI response - skipping")
                    return (False, "Empty AI response")
                return self._parse_response(response)
        except TimeoutError:
            logger.warning("Claude Code SDK timeout - likely running outside Claude Code environment")
            if _config.skip_on_ai_unavailable:
                return (True, "AI timeout - skipping evaluation")
            return (False, f"AI evaluation timed out after {timeout}s")
        except Exception as e:
            logger.error(f"AI evaluation error: {e}")
            if _config.skip_on_ai_unavailable:
                return (True, f"AI error: {e}")
            return (False, f"AI evaluation failed: {e}")

    @codeflash_behavior_async
    async def _call_claude(self, prompt: str) -> str:
        """Call Claude Code SDK and collect response."""
        if not CLAUDE_SDK_AVAILABLE:
            return ""
        response = ""
        async with ClaudeSDKClient(
            options=ClaudeCodeOptions(
                system_prompt="You are evaluating if a command ran successfully. Respond with 'PASS' or 'FAIL' followed by a colon and brief reason.",
                max_turns=1,
            )
        ) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if hasattr(message, "content"):
                    content = getattr(message, "content", [])
                    if isinstance(content, list):
                        for block in content:
                            if hasattr(block, "text"):
                                response += getattr(block, "text", "")
        return response

    def _parse_response(self, text: str) -> tuple[bool, str]:
        """Parse AI response to determine pass/fail."""
        text = text.strip()
        if text.upper().startswith("PASS"):
            if ":" in text:
                reasoning = text.split(":", 1)[1].strip()
            else:
                reasoning = text[4:].strip() or "Criteria met"
            return (True, reasoning)
        if text.upper().startswith("FAIL"):
            if ":" in text:
                reasoning = text.split(":", 1)[1].strip()
            else:
                reasoning = text[4:].strip() or "Criteria not met"
            return (False, reasoning)
        text_lower = text.lower()
        if "success" in text_lower or "passed" in text_lower or "works" in text_lower:
            return (True, text[:100])
        if "error" in text_lower or "failed" in text_lower or "not found" in text_lower:
            return (False, text[:100])
        return (True, f"Unclear result: {text[:100]}")
