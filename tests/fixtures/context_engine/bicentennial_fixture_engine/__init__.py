"""Offline fixture ContextEngine; importing this module does not require Hermes."""


def register(ctx):
    from agent.context_engine import ContextEngine

    class FixtureEngine(ContextEngine):
        name = "bicentennial_fixture_engine"

        def update_from_response(self, usage):
            pass

        def should_compress(self, prompt_tokens=None):
            return False

        def compress(self, messages, **kwargs):
            return messages

        def get_tool_schemas(self):
            return [{"name": "fixture_engine_probe", "description": "Offline fixture probe",
                     "parameters": {"type": "object", "properties": {}}}]

        def handle_tool_call(self, name, args, **kwargs):
            return '{"ok": true}'

    ctx.register_context_engine(FixtureEngine())
