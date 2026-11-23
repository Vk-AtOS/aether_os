"""Prime learning engine, L1 (KAN-229): one loop over the three learners (corrections, golden builds, fix memory).

    adapters  the common record (LearnedItem) over the three stores, and the calls that put items into prompts
    loop      record each use and its outcome; retire what keeps failing
    metrics   help rate per kind and week; build first-pass and correction rate trend
    models    learning_uses, learning_item_state, learning_build_outcomes

Organisation-level only: build and approval learnings, no per-person view.
"""
