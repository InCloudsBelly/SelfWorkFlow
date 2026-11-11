# 只读参考：evals.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "skill_name": "cpp-core",
  "evals": [
    {
      "id": 1,
      "prompt": "Review a C++ ownership refactor that moves callbacks onto a worker thread without changing the public ABI.",
      "expected_output": "Loads ownership and concurrency references, checks lifetime, thread ownership, ABI and focused tests.",
      "files": []
    },
    {
      "id": 2,
      "prompt": "Diagnose an Unreal native crash after GC while the project forbids local builds.",
      "expected_output": "Uses failure envelope, debugging and Unreal lenses, does not attach or claim a build, reports unverified checks.",
      "files": []
    },
    {
      "id": 3,
      "prompt": "Fix links in a Markdown C++ tutorial without changing code.",
      "expected_output": "Does not trigger cpp-core for a documentation-only task.",
      "files": []
    }
  ]
}

````
