"""Unit tests for transcript parsing and export (vtt/srt/md)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kazaa import transcripts  # noqa: E402

SAMPLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello &amp; welcome to the <c>demo</c>

00:00:05.500 --> 00:00:08.000
<v Speaker>Second line</v> of the talk

NOTE a comment should be ignored

00:01:00.000 --> 00:01:02.000
Final <00:01:01.000>cue
"""

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:04,000
Hello & welcome to the demo

2
00:00:05,500 --> 00:00:08,000
Second line of the talk

3
00:01:00,000 --> 00:01:02,000
Final cue
"""

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(tmp, exist_ok=True)

vtt_path = os.path.join(tmp, "sample.vtt")
srt_path = os.path.join(tmp, "sample.srt")
open(vtt_path, "w", encoding="utf-8").write(SAMPLE_VTT)
open(srt_path, "w", encoding="utf-8").write(SAMPLE_SRT)

cv = transcripts.parse_cues(vtt_path)
cs = transcripts.parse_cues(srt_path)

check("vtt parses 3 cues", len(cv) == 3)
check("srt parses 3 cues", len(cs) == 3)
check("vtt tags stripped", "<" not in cv[0][2] and "&amp;" not in cv[0][2])
check("vtt first text", cv[0][2] == "Hello & welcome to the demo")
check("vtt speaker tag stripped", cv[1][2] == "Second line of the talk")
check("vtt timestamp embedded tag stripped",
      cv[2][2] == "Final cue")
check("timestamps ~equal", abs(cv[0][0] - 1.0) < 0.01 and abs(cs[2][0] - 60.0) < 0.01)

md = transcripts.to_markdown(cv, title="Demo Talk", source_url="https://youtu.be/x",
                             lang="en")
check("md has heading", md.startswith("# Demo Talk"))
check("md has source", "- Source: https://youtu.be/x" in md)
check("md cue with timestamp", "- **[00:01]** Hello & welcome to the demo" in md)
check("md 1h+ fmt", "1:00:00" not in md and "[01:00]" in md)
check("md no raw tags", "<c>" not in md and "WEBVTT" not in md)

md_plain = transcripts.to_markdown(cv, with_timestamps=False)
check("md plain has no timestamps", "**[" not in md_plain and "Hello & welcome" in md_plain)

out_md = transcripts.convert(srt_path, "md", source_url="https://example.com/v")
check("convert srt->md file", os.path.exists(out_md) and open(out_md, encoding="utf-8").read().startswith("# sample"))
check("intermediate srt kept", os.path.exists(srt_path))

out_srt = transcripts.convert(vtt_path, "srt")
content = open(out_srt, encoding="utf-8").read()
check("convert vtt->srt", "00:00:01,000 --> 00:00:04,000" in content and content.startswith("1\n"))

out_vtt = transcripts.convert(srt_path, "vtt")
content = open(out_vtt, encoding="utf-8").read()
check("convert srt->vtt", content.startswith("WEBVTT") and "00:00:05.500" in content)

try:
    transcripts.convert(srt_path, "mp4")
    check("bad target raises", False)
except ValueError:
    check("bad target raises", True)

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL TRANSCRIPT TESTS PASSED")
