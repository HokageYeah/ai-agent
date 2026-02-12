import pytest
from app.memory.short_term import ShortTermMemory

def test_short_term_memory_ops():
    mem = ShortTermMemory(max_messages=3)
    cid = "test_conv"
    
    # 1. Test add & get
    mem.add_message(cid, {"role": "user", "content": "1"})
    context = mem.get_context(cid)
    assert len(context) == 1
    assert context[0]["content"] == "1"
    
    # 2. Test windowing
    mem.add_message(cid, {"role": "assist", "content": "2"})
    mem.add_message(cid, {"role": "user", "content": "3"})
    assert len(mem.get_context(cid)) == 3
    
    mem.add_message(cid, {"role": "assist", "content": "4"})
    context = mem.get_context(cid)
    assert len(context) == 3
    assert context[0]["content"] == "2" # FIFO
    assert context[-1]["content"] == "4"
    
    # 3. Test clear
    mem.clear(cid)
    assert len(mem.get_context(cid)) == 0

def test_short_term_memory_isolation():
    mem = ShortTermMemory()
    mem.add_message("c1", {"role": "user", "content": "1"})
    mem.add_message("c2", {"role": "user", "content": "2"})
    
    assert len(mem.get_context("c1")) == 1
    assert mem.get_context("c1")[0]["content"] == "1"
    assert len(mem.get_context("c2")) == 1
    assert mem.get_context("c2")[0]["content"] == "2"
