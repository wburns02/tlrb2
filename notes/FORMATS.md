# TLRB2 data formats

## Team file .V20 (11735 B, uncompressed)
295 B header + 80 player records x 143 B (verified: names land at 295 + 143*i).
Header: +0 team name (NUL padded), +16 stadium/surface code (e.g. "clCALgrass", "NASGRASS"). Rest TBD.
Player: +0 last name (12 B), +12 first name (12 B). +24.. TBD (ratings, positions, handedness, stats).
League index .MAJ: league name, then team file names (e.g. "ms01681" = file stem + 2-char code). Detail TBD.
Method: tools/v20.py diff after a single-field edit in Utilities (work install), one field per edit.

## Other files (TBD)
SYSTEM (76 B: current league name + settings), CONTROL (9 B: next program/state), GAME.TMP, .SCH schedules
(57176 B, text header "162 "), PLAYOFFS.AL/.NL, SCREENS/*.SCR, *.ANM, *.PAG, *.PAL, *.FNT, saved seasons.
