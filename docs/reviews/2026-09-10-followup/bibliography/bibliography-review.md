# Bibliography follow-up to Fable, 10 September 2026

**Scope:** all 107 entries in `docs/references.bib` (98 DOI, 9 without DOI), public git blob `318e934277ad507487f12c1708944346623fb9f4`. Retrieved all 98 DOI metadata records: **95 Crossref, 3 DataCite**. Reviewed every non-DOI entry against an originating institution, publisher, source manuscript, or software repository where available. This checks bibliographic identity, not whether each citation supports the scientific claim made in the twin.

**Disposition:** 96 verified; 8 require correction (6 substantive, 2 ancillary); 1 minor author-name normalization recommended; 1 software citation partially verified; 1 unpublished manuscript unresolved. No DOI was found to point to an unrelated work. That does **not** make the current bibliography accurate: five DOI entries contain incorrect or silently incomplete author lists.

## Corrections and unresolved records

| Key | Disposition | Evidence and required correction |
|---|---|---|
| `denolle2026unified` | unresolved | No DOI or source URL is supplied. Exact-title search did not locate an authoritative manuscript or publication record. Related author software describes an in-preparation manuscript, which does not verify this exact title or the claimed submitted status. Author should supply a dated manuscript record; absence of a public record is not evidence of fabrication.  |
| `clements2018tracking` | normalization recommended | Registered and publisher given name is Timothy, while bib uses Tim. Same paper and author identity; standardize to the published form rather than label this a fabricated citation. [source 1](https://api.crossref.org/works/10.1029/2018GL077706) [source 2](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2018GL077706) |
| `shi2026agroseismology` | correction required | Six of twelve published authors are omitted without an others marker: Nan You, Simon Jeffery, Joe Collins, Ana Prada Barrio, Paula A. Misiewicz, Tarje Nissen-Meyer. Restore the full registered author order. [source 1](https://api.crossref.org/works/10.1126/science.aec0970) [source 2](https://www.science.org/doi/10.1126/science.aec0970) |
| `jasechko2023rapid` | correction required | Issue number is 7996, not 7995. Title/authors/year/venue/DOI match. [source 1](https://api.crossref.org/works/10.1038/s41586-023-06879-8) [source 2](https://www.nature.com/nature/volumes/625/issues/7996) |
| `ma2025hydroframecode` | partially verified | Repository exists, was created 2025-05-06, is owned by HydroFrame-ML, names Yueling Ma as contact, and is explicitly linked by the 2026 paper as its code. GPL-3.0 is confirmed. Formal citation authorship/release version is not specified; a repository contact is insufficient to certify an exhaustive author list. Pin a commit/release and add citation metadata. [source 1](https://github.com/HydroFrame-ML/high-res-WTD-static) [source 2](https://api.github.com/repos/HydroFrame-ML/high-res-WTD-static) |
| `mckee1993spi` | correction required | Title, all three authors, conference, and 1993 year match the original paper. The 17 and 22 are January conference dates (17–22 January), not volume 17 and issue 22; remove those volume/number fields. [source 1](https://ccc.atmos.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf) [source 2](https://climate.colostate.edu/pubs.html) |
| `ramcharan2018soil` | correction required | Replace Sarah Davey and Sandra Parton with Sharon Waltman and Skye Wills (authors 5 and 6). [source 1](https://api.crossref.org/works/10.2136/sssaj2017.04.0122) [source 2](https://acsess.onlinelibrary.wiley.com/doi/full/10.2136/sssaj2017.04.0122) |
| `degraaf2015global` | correction required | Restore seven-author order: Inge E.M. de Graaf; Rens L.P.H. van Beek; Tom Gleeson; Nils Moosdorf; Oliver Schmitz; Edwin H. Sutanudjaja; Marc F.P. Bierkens. Current entry omits three middle authors, reorders remaining names, and gives van Beek a different given name. [source 1](https://api.crossref.org/works/10.1016/j.advwatres.2017.01.011) [source 2](https://dspace.library.uvic.ca/items/4f23cbfc-585e-4570-aaa4-ca268493272d) |
| `wadnr2016landslidemapping` | correction required | The actual linked fact sheet is dated December 2023, not 2016. Cite the linked edition as 2023 or supply an archived 2016 edition. Title, organizational authorship, and publisher match. [source 1](https://www.dnr.wa.gov/publications/ger_fs_landslide_for_planners.pdf) |
| `zhu2015geospatial` | correction required | Daniel Daley must be Davene Daley; Kevin L. Knudsen must be Keith L. Knudsen. [source 1](https://api.crossref.org/works/10.1193/121912eqs353m) [source 2](https://journals.sagepub.com/doi/10.1193/121912EQS353M) |
| `cook2009floodmapping` | correction required | Amanda Cook must be Aaron Cook. [source 1](https://api.crossref.org/works/10.1016/j.jhydrol.2009.08.015) |

The large errors are author attribution, not newly fabricated DOI strings. In particular, de Graaf's 2017 paper has seven authors in the registered order; the current four-name record is neither that complete list nor an explicitly shortened prefix. Shi's final Science article has twelve authors; six middle names were removed while the last author was retained. The explicit `and others` lists elsewhere are distinguished from these silent omissions.

## Why the current metadata task misses them

Replaying the unchanged `check_metadata()` against the freshly fetched Crossref records gives **98 entries, 0 mismatches, 3 skipped, exit 0**. All five substantive DOI-author defects pass the existing `metadata_mismatches()` function. Its author comparison checks only the first family name and an excessive-count threshold; it does not compare later authors, given names, their order, or omitted authors. See `scripts/check_doi_integrity.py:262` and `:268`.

The same real function, with metadata retrieval mocked unavailable for every DOI, skips **all 98 and still exits 0** (`:297`–`:315`). HTTP errors, outages and an actual non-Crossref registration collapse to the same `None`. This is an additional fail-open release-gate defect, reproduced without making another network request. Metadata mode also omits all nine non-DOI entries. Current CI calls `pixi run check-dois`, the resolution-only task (`.github/workflows/ci.yml:61`); `pixi run check-dois-metadata` already exists in `pixi.toml:79`, but neither its present implementation nor its successful exit is a full bibliography acceptance gate.

The fix should compare all named authors in order, require an explicit truncation marker when appropriate, resolve DataCite registrations, and distinguish unavailable evidence from accepted records. A checked-in, reviewed disposition should cover legitimate non-DOI sources and provider-specific variants; incomplete lookup coverage must not certify success. The bibliography should be corrected separately from claims about scientific validity. Existing standing integrity issue #25 and implemented checker issue #158 provide traceability; a new issue is not the only available route.

## False positives avoided and remaining limits

- USGS confirms the Wirth data release under the cited DOI and original author form. The current DataCite creator display uses Erin (Wirth) W Moriarty, and stores unsplit names. That is not a wrong-work DOI. `and` versus `&` in the title is also harmless.
- Beven's Crossref record appends a French translation; the English title is correct. Springer's Stein record confirms the subtitle omitted from Crossref's main-title field. Ribeiro's `Jr.` suffix does not make the Diggle book a different record.
- Supported online-first/print year splits were retained, rather than using an arbitrary plus/minus-one-year tolerance. `ma2023wtd` is online 2023 and issue 2024; its convention should be documented. Other two splits are already noted in the bibliography.
- Matérn's institutional record supplies a longer subtitle, but the core 1960 book identity and series are correct. Whittle's registered page field gives only the starting page; that is not proof the bibliography's full range is wrong.
- The Denolle–Lipovsky source HTML was fetched directly with HTTP 200 after the web reader could not open it. Its title, two author tags and `2026-08-10` date match. This verifies a project-hosted manuscript, not journal submission or review status. The separate `denolle2026unified` record remains unresolved because no exact source was located.
- The software repository and GPL-3.0 license match; its contact name and repository ownership do not establish exhaustive formal software authorship or a cited release. The record needs a pinned version/commit and citation metadata.

Read-only metadata queries initially encountered a permission rejection. Live GitHub checks proved the complete local bibliography byte-for-byte identical to the public main blob; the same action was then approved. Crossref rate limits were handled by sequential retries. No GitHub records, source code, or bibliography entries were changed. Per-request timestamps were not retained; each disposition records the retrieval date, source URL, and normalized metadata hash.

## Entry-by-entry evidence

The complete normalized primary records and dispositions are in [bibliography-entry-dispositions.json](bibliography-entry-dispositions.json). The unchanged checker replay is in [existing-checker-cached-replay.txt](existing-checker-cached-replay.txt), and its controlled counterexamples are in [checker-gap-probes.json](checker-gap-probes.json). The raw provider responses remain temporary working evidence and are not needed in the repository.

| Entry | Disposition | Primary evidence |
|---|---|---|
| `waldallen2007` | verified | [record 1](https://api.crossref.org/works/10.1785/0120060267) |
| `grant2025svm` | verified | [record 1](https://api.crossref.org/works/10.26443/seismica.v4i2.1672) |
| `wirth2025svmdata` | verified | [record 1](https://api.datacite.org/dois/10.5066/P14HJ3IC) [record 2](https://www.usgs.gov/data/data-a-3-d-seismic-velocity-model-cascadia-shallow-soils-topography-version-17) |
| `denolle2026unified` | unresolved | No exact authoritative record located |
| `biot1941general` | verified | [record 1](https://api.crossref.org/works/10.1063/1.1712886) |
| `senss2006passive` | verified | [record 1](https://api.crossref.org/works/10.1029/2006GL027797) |
| `clements2018tracking` | normalization recommended | [record 1](https://api.crossref.org/works/10.1029/2018GL077706) [record 2](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2018GL077706) |
| `shapiro2005high` | verified | [record 1](https://api.crossref.org/works/10.1126/science.1108339) |
| `clements2023seismic` | verified | [record 1](https://api.crossref.org/works/10.1029/2022JB025553) |
| `shi2026agroseismology` | correction required | [record 1](https://api.crossref.org/works/10.1126/science.aec0970) [record 2](https://www.science.org/doi/10.1126/science.aec0970) |
| `fan2013global` | verified | [record 1](https://api.crossref.org/works/10.1126/science.1229881) |
| `fan2019topographic` | verified | [record 1](https://api.crossref.org/works/10.1029/2018WR023903) |
| `bloomfield2013analysis` | verified | [record 1](https://api.crossref.org/works/10.5194/hess-17-4769-2013) |
| `cuthbert2019global` | verified | [record 1](https://api.crossref.org/works/10.1038/s41558-018-0386-4) |
| `kuss2014multi` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2014.09.069) |
| `wunsch2021groundwater` | verified | [record 1](https://api.crossref.org/works/10.5194/hess-25-1671-2021) |
| `marcais2017prospecting` | verified | [record 1](https://api.crossref.org/works/10.1111/gwat.12557) |
| `taylor2012ground` | verified | [record 1](https://api.crossref.org/works/10.1038/nclimate1744) |
| `nobre2011hand` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2011.03.051) |
| `gharari2011toward` | verified | [record 1](https://api.crossref.org/works/10.5194/hess-15-3275-2011) |
| `beven1979physically` | verified | [record 1](https://api.crossref.org/works/10.1080/02626667909491834) |
| `ma2023wtd` | verified | [record 1](https://api.crossref.org/works/10.1111/gwat.13362) |
| `liesch2019aquifer` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2019.02.060) |
| `jasechko2023rapid` | correction required | [record 1](https://api.crossref.org/works/10.1038/s41586-023-06879-8) [record 2](https://www.nature.com/nature/volumes/625/issues/7996) |
| `reinecke2020importance` | verified | [record 1](https://api.crossref.org/works/10.1111/gwat.12996) |
| `heudorfer2019groundwater` | verified | [record 1](https://api.crossref.org/works/10.1029/2018WR024418) |
| `konapala2020hybrid` | verified | [record 1](https://api.crossref.org/works/10.1088/1748-9326/aba927) |
| `sanger2025liquefaction` | verified | [record 1](https://api.datacite.org/dois/10.48550/arXiv.2509.10965) |
| `sanger2025parametric` | verified | [record 1](https://api.datacite.org/dois/10.48550/arXiv.2510.00372) |
| `ma2026highres` | verified | [record 1](https://api.crossref.org/works/10.1038/s43247-025-03094-3) |
| `bennett2024emulator` | verified | [record 1](https://api.crossref.org/works/10.1029/2023MS004095) |
| `tran2021emulator` | verified | [record 1](https://api.crossref.org/works/10.3390/w13233393) |
| `ma2025hydroframecode` | partially verified | [record 1](https://github.com/HydroFrame-ML/high-res-WTD-static) [record 2](https://api.github.com/repos/HydroFrame-ML/high-res-WTD-static) |
| `rodriguez2014nitrate` | verified | [record 1](https://api.crossref.org/works/10.1016/j.scitotenv.2014.01.001) |
| `roberts2017crossval` | verified | [record 1](https://api.crossref.org/works/10.1111/ecog.02881) |
| `vonasmuth2002tfn` | verified | [record 1](https://api.crossref.org/works/10.1029/2001WR001136) |
| `bakker2019timeseries` | verified | [record 1](https://api.crossref.org/works/10.1111/gwat.12927) |
| `collenteur2019pastas` | verified | [record 1](https://api.crossref.org/works/10.1111/gwat.12925) |
| `brutsaert1977recession` | verified | [record 1](https://api.crossref.org/works/10.1029/WR013i003p00637) |
| `shen2018deeplearning` | verified | [record 1](https://api.crossref.org/works/10.1029/2018WR022643) |
| `ke2017lightgbm` | verified | [record 1](https://proceedings.neurips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html) |
| `hengl2007regression` | verified | [record 1](https://api.crossref.org/works/10.1016/j.cageo.2007.05.001) |
| `li2011review` | verified | [record 1](https://api.crossref.org/works/10.1016/j.ecoinf.2010.12.003) |
| `maxwell2015connections` | verified | [record 1](https://api.crossref.org/works/10.1126/science.aaf7891) |
| `scanlon2002choosing` | verified | [record 1](https://api.crossref.org/works/10.1007/s10040-001-0176-2) |
| `mckee1993spi` | correction required | [record 1](https://ccc.atmos.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf) [record 2](https://climate.colostate.edu/pubs.html) |
| `ramcharan2018soil` | correction required | [record 1](https://api.crossref.org/works/10.2136/sssaj2017.04.0122) [record 2](https://acsess.onlinelibrary.wiley.com/doi/full/10.2136/sssaj2017.04.0122) |
| `degraaf2015global` | correction required | [record 1](https://api.crossref.org/works/10.1016/j.advwatres.2017.01.011) [record 2](https://dspace.library.uvic.ca/items/4f23cbfc-585e-4570-aaa4-ca268493272d) |
| `saxton2006soil` | verified | [record 1](https://api.crossref.org/works/10.2136/sssaj2005.0117) |
| `abatzoglou2018terraclimate` | verified | [record 1](https://api.crossref.org/works/10.1038/sdata.2017.191) |
| `thornthwaite1957water` | verified | [record 1](https://www.wrc.udel.edu/wp-content/publications/ThornthwaiteandMather1957Instructions_Tables_ComputingPotentialEvapotranspiration_Water%20Balance.pdf) |
| `nauman2024solus` | verified | [record 1](https://api.crossref.org/works/10.1002/saj2.20769) |
| `pacheco2005time` | verified | [record 1](https://api.crossref.org/works/10.1121/1.2000827) |
| `koolparker1987` | verified | [record 1](https://api.crossref.org/works/10.1029/WR023i001p00105) |
| `illien2022gorkha` | verified | [record 1](https://api.crossref.org/works/10.1029/2021JB023402) |
| `wang2021healing` | verified | [record 1](https://api.crossref.org/works/10.1038/s41467-021-21418-7) |
| `illien2025recovery` | verified | [record 1](https://api.crossref.org/works/10.1038/s41467-025-57151-8) |
| `bauer2021digitaltwin` | verified | [record 1](https://api.crossref.org/works/10.1038/s41558-021-00986-y) |
| `li2023bigdata` | verified | [record 1](https://api.crossref.org/works/10.1038/s43017-023-00409-w) |
| `doblasreyes2026destine` | verified | [record 1](https://api.crossref.org/works/10.5194/gmd-19-2821-2026) |
| `rigon2022darth` | verified | [record 1](https://api.crossref.org/works/10.5194/hess-26-4773-2022) |
| `barros2024dte` | verified | [record 1](https://api.crossref.org/works/10.3389/fsci.2024.1383659) |
| `wang2024massconserving` | verified | [record 1](https://api.crossref.org/works/10.1029/2023WR036461) |
| `wang2009constrainedenkf` | verified | [record 1](https://api.crossref.org/works/10.1029/2008WR007401) |
| `khaki2018waterbudget` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2018.06.080) |
| `springer2026grace` | verified | [record 1](https://api.crossref.org/works/10.5194/hess-30-985-2026) |
| `gruber2016triplecollocation` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jag.2015.09.002) |
| `saltelli2024backtoearth` | verified | [record 1](https://api.crossref.org/works/10.1002/wcc.915) |
| `hazeleger2024humans` | verified | [record 1](https://api.crossref.org/works/10.1038/s43247-024-01626-x) |
| `denolle2026seishydro` | verified | [record 1](https://gaia-hazlab.github.io/seis-hydro-2-sed/paper/paper.html) |
| `montgomery1994shalstab` | verified | [record 1](https://api.crossref.org/works/10.1029/93WR02979) |
| `claessens2005demresolution` | verified | [record 1](https://api.crossref.org/works/10.1002/esp.1155) |
| `wadnr2016landslidemapping` | correction required | [record 1](https://www.dnr.wa.gov/publications/ger_fs_landslide_for_planners.pdf) |
| `zhu2015geospatial` | correction required | [record 1](https://api.crossref.org/works/10.1193/121912eqs353m) [record 2](https://journals.sagepub.com/doi/10.1193/121912EQS353M) |
| `zhu2017geospatial` | verified | [record 1](https://api.crossref.org/works/10.1785/0120160198) |
| `idriss2006liquefaction` | verified | [record 1](https://api.crossref.org/works/10.1016/j.soildyn.2004.11.023) |
| `cook2009floodmapping` | correction required | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2009.08.015) |
| `roe2003orographic` | verified | [record 1](https://api.crossref.org/works/10.1029/2001JB001521) |
| `matern1960spatial` | verified | [record 1](https://research.slu.se/en/publications/spatial-variation-stochastic-models-and-their-application-to-some/) |
| `whittle1954stationary` | verified | [record 1](https://api.crossref.org/works/10.2307/2332724) |
| `guttorp2006matern` | verified | [record 1](https://api.crossref.org/works/10.1093/biomet/93.4.989) |
| `handcock1993bayesian` | verified | [record 1](https://api.crossref.org/works/10.1080/00401706.1993.10485354) |
| `stein1999interpolation` | verified | [record 1](https://api.crossref.org/works/10.1007/978-1-4612-1494-6) [record 2](https://link.springer.com/book/10.1007/978-1-4612-1494-6) |
| `zhang2004inconsistent` | verified | [record 1](https://api.crossref.org/works/10.1198/016214504000000241) |
| `lindgren2011explicit` | verified | [record 1](https://api.crossref.org/works/10.1111/j.1467-9868.2011.00777.x) |
| `minasny2005matern` | verified | [record 1](https://api.crossref.org/works/10.1016/j.geoderma.2005.04.003) |
| `gneiting2010matern` | verified | [record 1](https://api.crossref.org/works/10.1198/jasa.2010.tm09420) |
| `gelhar1993stochastic` | verified | [record 1](https://cee.mit.edu/people_individual/lynn-gelhar/) |
| `dagan1989flow` | verified | [record 1](https://api.crossref.org/works/10.1007/978-3-642-75015-1) |
| `mizell1982spectral` | verified | [record 1](https://api.crossref.org/works/10.1029/WR018i004p01053) |
| `rubin2003applied` | verified | [record 1](https://api.crossref.org/works/10.1093/oso/9780195138047.001.0001) |
| `western2002scaling` | verified | [record 1](https://api.crossref.org/works/10.1146/annurev.earth.30.091201.140434) |
| `vereecken2014soilmoisture` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2013.11.061) |
| `diggle2007modelbased` | verified | [record 1](https://api.crossref.org/works/10.1007/978-0-387-48536-2) [record 2](https://link.springer.com/book/10.1007/978-0-387-48536-2) |
| `bolin2020rational` | verified | [record 1](https://api.crossref.org/works/10.1080/10618600.2019.1665537) |
| `haitjema2005subdued` | verified | [record 1](https://api.crossref.org/works/10.1111/j.1745-6584.2005.00090.x) |
| `varouchakis2019spatiotemporal` | verified | [record 1](https://api.crossref.org/works/10.1016/j.jhydrol.2019.05.055) |
| `varouchakis2022complex` | verified | [record 1](https://api.crossref.org/works/10.1029/2021WR029988) |
| `ryu2005footprint` | verified | [record 1](https://api.crossref.org/works/10.1029/2004WR003835) |
| `zhang2023oklahoma` | verified | [record 1](https://api.crossref.org/works/10.1029/2023GL103419) |
| `lu2025deepsoilmoisture` | verified | [record 1](https://api.crossref.org/works/10.1029/2025GL117302) |
| `feng2026utah` | verified | [record 1](https://api.crossref.org/works/10.1029/2024JB030689) |
| `zhang2025oklahomamapping` | verified | [record 1](https://api.crossref.org/works/10.1029/2025GL115201) |
| `thompson2007vscorrelation` | verified | [record 1](https://api.crossref.org/works/10.1016/j.soildyn.2006.05.004) |
| `thomson2020canterbury` | verified | [record 1](https://api.crossref.org/works/10.1016/j.soildyn.2019.105834) |
| `bogaard2016landslidehydrology` | verified | [record 1](https://api.crossref.org/works/10.1002/wat2.1126) |
| `pelascini2022hillslope` | verified | [record 1](https://api.crossref.org/works/10.5194/nhess-22-3125-2022) |
