# Code quality baseline

An **observed baseline failure** was captured from a real Agent task on 2026-08-11. The old workflow called a test bridge the narrowest compatible owner-layer change after a test could not reuse a translation-unit-private renderer processor. It then allowed a public EMeshPass test-only enum slot, conditionally changed the enum count and registration matrix, and spread test-only branches through the production Renderer path. Multiple correctness reviews did not reject that intrusion.

The failure demonstrates that the old generic rule was insufficient: it did not require an explicit impact-radius budget, did not prevent test coverage from shaping public production contracts, and did not force comparison with a test-owned seam or black-box verification before crossing that boundary. The new pressure scenarios preserve this concrete failure class without depending on project-specific names.

An additional pressure test on 2026-08-14 exposed a scope loophole in that revised rule. Given an approved Plan for one parser fix, the Agent chose to repair a different private cache defect without confirmation because it blocked a broad module regression and still fit the owner and intrusion budget. The Plan-boundary scenario preserves this observed failure: an unplanned behavior change requires re-planning even when it is local, small, and needed to make a broad test command green.

The selected reference repository was dirty overall at revision `4b76abd32ff34231c542e2fad0b4388dea61c622`; the five selected files were individually tracked and clean. Their hashes are recorded in `imports/extraction-records/code-quality-v1.yaml`.
