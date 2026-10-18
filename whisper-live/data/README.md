# HSK vocabulary data

HSK 3.0 **2021 grading standard** (GF 0025-2021), not the 2025 exam syllabus.
Source: [HSK University word list](https://github.com/ayman-ezz/hsk-3.0-word-list/tree/8c79c71915c25a80e5e68aacec940449b36060d8)
by HSK University (https://hskuniversity.com), revision `8c79c71915c25a80e5e68aacec940449b36060d8`.

`hsk.json` reduces the source `data/all.jsonl` to a map from headword to
`[minimum_band, pinyin]`. Combined band 7–9 is stored as 7. Duplicate headwords
keep the lowest band and its pinyin; meanings are not disambiguated. The source's
11,092 entries produce 10,946 distinct headwords. Source-normalized forms are
used unchanged; optional spellings are not expanded.

Compilation: CC BY 4.0; see HSK-LICENSE.txt. The underlying machine-readable
source also carries the MIT notice in HSK-NOTICE.txt. No endorsement is implied.
There are no English dictionary definitions in this data.
