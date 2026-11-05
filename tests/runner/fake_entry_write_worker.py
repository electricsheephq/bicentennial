"""The life double with a synthetic provider's tool names and argument shapes."""

import json

import fake_life_worker as worker

request, execute = worker.request, worker.execute


def provider_request(cfg, messages, tools, **kwargs):
    offered = []
    for tool in tools:
        function = dict(tool["function"])
        if function["name"] == "memory":
            function.update(name="entry_store", parameters=dict(type="object",
                properties=dict(content=dict(type="string")), required=["content"]))
            offered.append(dict(type="function", function=dict(name="entry_remove", parameters=dict(type="object",
                properties=dict(memory_id=dict(type="string")), required=["memory_id"]))))
        elif function["name"] == "session_search":
            function.update(name="entry_search", parameters=dict(type="object", properties=dict(
                query=dict(type="string"), whole=dict(type="boolean")), required=["query"]))
        offered.append(dict(type="function", function=function))
    return request(cfg, messages, offered, **kwargs)


def provider_execute(call, memory, servers, cwd):
    function = call["function"]
    if function["name"] == "entry_store":
        args = json.loads(function["arguments"])
        assert set(args) == {"content"}
        call = dict(call, function=dict(function, name="memory", arguments=json.dumps(dict(action="add", **args))))
    return execute(call, memory, servers, cwd)


if __name__ == "__main__":
    worker.request, worker.execute = provider_request, provider_execute
    worker.main()
