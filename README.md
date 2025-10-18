**PyInspect is a Python RPC backend and inspection toolkit working thread-free.**

It provides a powerful, asynchronous backend to dynamically inspect, hook, and manipulate running Python applications without blocking or creating new threads. It's designed for building advanced debuggers, analysis tools, and live-editing environments.

## Features

PyInspect allows you to remotely and non-intrusively interact with a live Python process.

  * **⚡️ Thread-Free & Async:** Built on `asyncio`, PyInspect runs in your application's existing event loop. It's non-blocking, and you may use it in case you don't want to expose what you are doing to a certain Python application.
  * **📡 RPC Backend:** All functionalities are exposed via an RPC interface, allowing you to build custom clients (GUIs, CLIs, web dashboards) to interact with your application.
  * **🪝 Comprehensive Hooking:** Dynamically hook any Python target:
      * Regular functions and methods
      * Built-in functions (e.g., `open`, `len`)
      * Methods on specific class instances
  * **GHOST Inspector:**
      * Inspect the **internal call trace** *within* a hooked function to see what it's doing inside.
  * **🕵️ Call Stack Analysis:**
      * Inspect the full function **call chain (stack)** for any hooked call.
  * **📝 Live Variable Editing:**
      * Get and set variable values within any loaded module in real-time.
  * **🔎 Object Search & Manipulation:**
      * Find all live instances of a specific class.
      * Inspect, modify attributes, and invoke methods on found objects.
  * **🖥️ Remote REPL:**
      * Simulate a Python interpreter (REPL) within the context of the running application for arbitrary code execution.

## How to use
1. Place all files in a folder.
2. Try to get target's pointers of `PyRun_SimpleString` , `PyGILState_Ensure` and `PyGILState_Release`
3. Import `server.py` and then run `start_server_and_patch` using `PyRun_SimpleString`. You need a `tick` function to be hooked in target, otherwise you may setup a thread to run this toolkit, which is suspicious to (potential) anti-cheat service.
4. Open `127.0.0.1:8888`, you will see the backend api is running.

## Contributing

Contributions are welcome\! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
