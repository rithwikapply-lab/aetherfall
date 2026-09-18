# Aetherfall

Aetherfall is an AI Dungeon Master and interactive-fiction engine that models world state as a persistent relational database rather than a growing chat transcript. Every narrative turn runs through a specialized agent pipeline that computes and commits structured state transitions, while a branching story graph records decisions as nodes in a tree to support seamless forking and state rewind without overwriting history.
