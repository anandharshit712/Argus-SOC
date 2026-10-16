"""Argus SOC backend API (Workstream C): the REST API the analyst UI calls.

It reaches the graph only through the graph tools library (`from argus_soc import graph`),
never with Cypher of its own (rule 1).
"""
