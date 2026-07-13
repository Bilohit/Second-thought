from note_hash import body_hash, dedup_key

def test_body_hash_ignores_frontmatter():
    a = "---\ntags: [x]\n---\nHello world\n"
    b = "---\ntags: [y]\ncategory: z\n---\nHello world\n"   # different frontmatter, same body
    assert body_hash(a) == body_hash(b)

def test_body_hash_changes_with_body():
    a = "---\nt: 1\n---\nHello\n"
    b = "---\nt: 1\n---\nHello!\n"
    assert body_hash(a) != body_hash(b)

def test_dedup_key_combines_id_and_body():
    raw = "---\nt: 1\n---\nBody\n"
    assert dedup_key("01ABC", raw) == "01ABC:" + body_hash(raw)
