# Lane B (dynamic) status

## Status 2026-10-06 (fourth Lane B session)
Done (evidence in FORMATS.md "GAME.TMP session 4", code names in lane_names.tsv)
- GAME.TMP lineup/defense/pitching block fully decoded (6763..7139, side 0 visitor, side 1 home); tools/lane_b/gt_decode.py verifies it against V20 headers on 14 captured runs.
- Ground Rules found: GAME.TMP 7428..7439 (pipes, errors, injuries, stats, one pitch, replays, sound, voice/crowd, music, quick off field, scrolling, animation speed), DH at 7193, night at 7143.
  Persisted by MAIN in SYSTEM bytes 8..0x19. Static (BB 7000:24b0, 7000:231f) and dynamic (single-switch diff runs from an all-YES baseline) agree.
- "Overall rating" is the salary (record +25). tools/ratings.salary(): batters 1185/1188 exact, pitchers 772/792 (rest off by 2..6 or a few outliers).
Open
- GAME.TMP play log (bytes 0..4799 counters, 4822..6762 six byte entries) not decoded; needs a saved long game with a known box score.
- Salary: pitcher 2..6 off residual (likely ERA or truncation detail), 3 batter and 4 pitcher outliers.
- Player record u16@27, u16@90/92, +0x85 counter (task 4 not started; earlier searches found no hit in this struct).
- Visitor auto-play bits 7444/7445, source of music byte 7436 in SYSTEM; header +237..244 labels; NL SCH row order.
Next
- Chase the pitcher residual by single-stepping f697 on one miss (Carlton 5934 vs 5939). Then task 4 via debugger watchpoints on a record.
Code addresses (BACK DGROUP 2c71 unless noted): see session 3 list in git history plus lane_names.tsv; new this session: BB 7000:231f, 7000:24b0, UTIL 5000:f382/f697/a5aa/a719/f687, 1000:9e5f/9ab9/9ae2/9bea/9c3c/9d04/9cc5/9d43.
State: my DOSBox-X killed; work SYSTEM restored from snaps/m3_base.
