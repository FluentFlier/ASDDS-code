# ASDDS citation and artifact reference

Use this repository to find citation-ready metadata and identify which part of
the ASDDS research archive supports a result. The actual research archive
remains private; this repository contains no raw or cleaned data, analysis code,
figures, manuscript files, or correspondence.

## Cite the archive

The preferred citation, formatted for copy/paste, is in [`CITATION.md`](CITATION.md).
GitHub also reads [`CITATION.cff`](CITATION.cff) and offers APA and BibTeX in
**Cite this repository**. A standalone BibTeX entry is in
[`CITATION.bib`](CITATION.bib).

The citation identifies the exact ASDDS Git commit `a223963`
([full commit](https://github.com/FluentFlier/ASDDS/commit/a223963cd1da8d89148b502b7b12af6d4eefb553)).
The canonical repository is [`FluentFlier/ASDDS`](https://github.com/FluentFlier/ASDDS).
It is private, so readers need an invitation to inspect the cited materials.

## Find the supporting artifact

Cite the archive once, then name the exact path and commit for each artifact used.
For numerical cleaning totals, cite the manifest; for a specific row or source,
include the corresponding record audit and source filename.

| Use | ASDDS artifact |
|---|---|
| Focused 34-session rescue outputs and totals | `json files to be rescued/cleaned/rescue_manifest.json` |
| Focused rescue row provenance | `json files to be rescued/cleaned/rescue_record_audit.json` |
| Remaining cleaned primary logs and totals | `bee_motion_logs/cleaned/cleaning_manifest.json` |
| Remaining primary row provenance | `bee_motion_logs/cleaned/cleaning_record_audit.json` |
| Cleaning rules and schema descriptions | `docs/DATA_AND_CLEANING.md` |
| Decisions and unresolved scientific choices | `docs/DECISIONS.md` and `docs/PROFESSOR_REVIEW.md` |
| Acquisition and rescue software | `code/` and `rescue_sleep_logs.py` |
| MATLAB comparison method | `matlab/` |
| Derived condition plots | `output/pdf/` |
| Working manuscript for coauthor review | `output/professor_handoff_20260722/ASDDS_manuscript_for_professor_review.pdf` |

Use a commit-specific URL of the form
`https://github.com/FluentFlier/ASDDS/blob/a223963cd1da8d89148b502b7b12af6d4eefb553/PATH`.
Replace `PATH` with the artifact path, URL-encoding spaces. The cited commit is
an archived repository snapshot; current working notes may have changed since
that commit.

## Publication and access limits

This is a working coauthor-review archive, not a DOI-backed publication or a
final biological dataset. No associated paper DOI or data DOI is claimed here.
Author order and reuse licenses have not been confirmed. Do not infer treatment
conditions from filenames or treat lower-bound endpoints as known wake times.
The archive documents remaining scientific and provenance limitations.

A persistent DOI should be assigned to a cleared, fixed release of the actual
research archive, with confirmed authors and license. The public citation
reference itself is not a substitute for that archival release.
