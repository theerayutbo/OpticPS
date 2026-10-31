# Clean-room declaration

Updated 2026-10-31. This is a description of the development process and of what is known about exposure. It is not a legal opinion, a legal guarantee or a certification of any kind.

## 1. Original OpticPS development process (v1.0 to v1.2)

As recorded when the project was built:

- OpticPS was written from published equations, standards and general communication theory.
- The four background repositories named at the time (OptiCommPy, Probabilistic_Constellation_Shaping, PAM4Receiver, OpticalSimulation) were not cloned or opened. Only their licence metadata was read through the GitHub API.
- OptiCommPy (GPL-3.0) is not a dependency and is not installed. `scripts/license_audit.py` fails the build on any GPL, LGPL or AGPL package.
- Development was AI-assisted (Claude Code; a separate Fable model pass reviewed the design).

## 2. Later exposure in comparison discussions

After the original development, ChatGPT and reviewers took part in comparison discussions in which parts of OptiCommPy were shown or described. That comparison was not used as a specification for OpticPS. The roadmap that governs the current work (v2, section B) forbids using it, or any memory of third-party source, as an algorithm specification, and requires features to be derived from original literature and standards.

This declaration does not state who took part in those discussions or what each person saw.

## 3. Limits of what can be claimed

- During the work from v1.3 onward, deliberate search for, retrieval of and recall of OptiCommPy and other optical simulator code was avoided. Agents were not instructed to look at it.
- OpticPS is developed with AI assistance. An AI-assisted process cannot certify that nothing was influenced indirectly by the model's training data. No such certification is given.
- No claim is made that nobody involved in the project has ever viewed competitor code.
- Dependency licence scanning (`docs/DEPENDENCY_AUDIT.md`, `docs/DEPENDENCY_EXCEPTIONS.md`) checks metadata. Licence metadata does not prove clean-room provenance.

## 4. Safeguards, and what is not done

Independent implementation from literature, licence scanning, provenance records (`docs/ALGORITHM_PROVENANCE.md`) and human legal review are distinct safeguards. The first three have been done in whatever form this repository records. **Human legal review has not been done.** Review of copyright, derivative-work questions and University of Manchester IP and ownership policy remains with a qualified human; the copyright holder owns that decision.

If code from another simulator is ever seen by an agent working on this repository, the affected work stops, the date and scope are recorded without pasting the code, and an independent reviewer takes over, as set out in roadmap v2 section B.
