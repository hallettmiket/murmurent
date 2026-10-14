# Reporting guidelines for prediction models and marker studies

**Status:** sourced 2026-10-14 (issue #155). The licence reading below was
approved by Mike Hallett on 2026-10-14: TRIPOD+AI's explicit CC BY 4.0
statement governs, over the "No commercial re-use" line in the page footer.

The [adversary](agents.md#adversary) checks written-up clinical prediction
models and prognostic marker studies against these checklists. It may not
browse and must not recite a checklist from memory, so this file is its only
source: an item number it reports has to be one listed here. The
[bookworm](agents.md#bookworm) keeps this file. Every item below was loaded
from the published source on the date shown, not typed from memory.

## Which checklist

| The work | Reporting | Risk of bias |
|---|---|---|
| A model predicting an individual's diagnosis or outcome, by regression or machine learning, developed or evaluated | **TRIPOD+AI** (27 items) | **PROBAST+AI** (4 domains) |
| A single marker's prognostic value, including marker-by-marker screens | **REMARK** (20 items) | none; the adversary reviews the methods as usual |
| A model built from markers first screened one at a time | TRIPOD+AI, and REMARK for the screen | PROBAST+AI |

Not covered here, named only: CONSORT (randomised trials), STROBE
(observational studies), STARD (diagnostic accuracy studies).

## Licences and what this file reproduces

| Checklist | Licence | In this file |
|---|---|---|
| TRIPOD+AI | CC BY 4.0 (with a conflicting footer, see its section) | item text verbatim, with attribution |
| PROBAST+AI | CC BY-NC 4.0 (non-commercial) | **paraphrased**, one line per question |
| REMARK | CC BY 4.0 (2005) and CC BY (2012) | item text verbatim (2012 wording), with attribution |

**Changes made to the verbatim material:** reformatted as tables; footnote
symbols moved; REMARK given in its 2012 wording only, with the differences from
2005 noted. Licences: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

---

## TRIPOD+AI

### Citation
Collins GS, Moons KGM, Dhiman P, Riley RD, Beam AL, Van Calster B, Ghassemi M, Liu X, Reitsma JB, van Smeden M, et al. (24 authors in total). TRIPOD+AI statement: updated guidance for reporting clinical prediction models that use regression or machine learning methods. BMJ 2024;385:e078378.
- DOI: 10.1136/bmj-2023-078378 (PMID 38626948, PMCID PMC11019967)
- URLs: https://doi.org/10.1136/bmj-2023-078378 (resolves to bmj.com, 403 to bots); loaded: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11019967/fullTextXML (PMC copy, https://pmc.ncbi.nlm.nih.gov/articles/PMC11019967/)
- Checked: 2026-10-14

### Licence
Quoted from the loaded article: "This is an Open Access article distributed in accordance with the terms of the Creative Commons Attribution (CC BY 4.0) license, which permits others to distribute, remix, adapt and build upon this work, for commercial use, provided the original work is properly cited. See: http://creativecommons.org/licenses/by/4.0/."

The same article's copyright line reads: "© Author(s) (or their employer(s)) 2019. Re-use permitted under CC BY. No commercial re-use. See rights and permissions. Published by BMJ."

**Reading.** The explicit licence statement is CC BY 4.0, which allows reproduction in a public repository with attribution (credit, a link to the licence, and a note if changed). The copyright line contains a contradictory phrase, "No commercial re-use", which looks like a BMJ footer template (it also says 2019, five years before publication, and is the same line that appears on the CC BY-NC PROBAST+AI paper). I treat the licence statement as controlling, but this is a genuine ambiguity in the source. If a conservative reading is wanted, ask BMJ rights or use the checklist as published by the TRIPOD group (tripod-statement.org), which I did not load.

### Checklist (Table 2 of the paper): 27 numbered items, 52 lines counting sub-items
Numbering is exactly as the source. Note on the marker column: the source labels it "Development/evaluation" and uses **D** (development only), **E** (evaluation only) and **D;E** (both). It does not use "V".

Source footnotes (verbatim): "D=items relevant only to the development of a prediction model; E=items relating solely to the evaluation of a prediction model; D;E=items applicable to both the development and evaluation of a prediction model. †Separately for all model building approaches. ‡TRIPOD-Cluster is a checklist of reporting recommendations for studies developing or validating models that explicitly account for clustering or explore heterogeneity in model performance (eg, at different hospitals or centres). §Relates to the analysis code, for example, any data cleaning, feature engineering, model building, and evaluation. ¶Relates to the code to implement the model to get estimates of risk for a new individual."

The footnote symbols attach to items 12c (†), 12d and 23b (‡), 18f (§) and 22 (¶) in the source; they were stripped by the parser from the item text below, so the symbols appear in the item text where the source placed them. Section headings in the source: Title, Abstract, Introduction, Methods, Open science, Patient and public involvement, Result (sic, singular in the source), Discussion. The "Section / topic" column below gives heading / topic.

| Item | Section / topic | D/E | Item text (verbatim) |
|---|---|---|---|
| 1 | Title / Title | D;E | Identify the study as developing or evaluating the performance of a multivariable prediction model, the target population, and the outcome to be predicted |
| 2 | Abstract / Abstract | D;E | See TRIPOD+AI for Abstracts checklist |
| 3a | Introduction / Background | D;E | Explain the healthcare context (including whether diagnostic or prognostic) and rationale for developing or evaluating the prediction model, including references to existing models |
| 3b | Introduction / Background | D;E | Describe the target population and the intended purpose of the prediction model in the context of the care pathway, including its intended users (eg, healthcare professionals, patients, public) |
| 3c | Introduction / Background | D;E | Describe any known health inequalities between sociodemographic groups |
| 4 | Introduction / Objectives | D;E | Specify the study objectives, including whether the study describes the development or validation of a prediction model (or both) |
| 5a | Methods / Data | D;E | Describe the sources of data separately for the development and evaluation datasets (eg, randomised trial, cohort, routine care or registry data), the rationale for using these data, and representativeness of the data |
| 5b | Methods / Data | D;E | Specify the dates of the collected participant data, including start and end of participant accrual; and, if applicable, end of follow-up |
| 6a | Methods / Participants | D;E | Specify key elements of the study setting (eg, primary care, secondary care, general population) including the number and location of centres |
| 6b | Methods / Participants | D;E | Describe the eligibility criteria for study participants |
| 6c | Methods / Participants | D;E | Give details of any treatments received, and how they were handled during model development or evaluation, if relevant |
| 7 | Methods / Data preparation | D;E | Describe any data pre-processing and quality checking, including whether this was similar across relevant sociodemographic groups |
| 8a | Methods / Outcome | D;E | Clearly define the outcome that is being predicted and the time horizon, including how and when assessed, the rationale for choosing this outcome, and whether the method of outcome assessment is consistent across sociodemographic groups |
| 8b | Methods / Outcome | D;E | If outcome assessment requires subjective interpretation, describe the qualifications and demographic characteristics of the outcome assessors |
| 8c | Methods / Outcome | D;E | Report any actions to blind assessment of the outcome to be predicted |
| 9a | Methods / Predictors | D | Describe the choice of initial predictors (eg, literature, previous models, all available predictors) and any pre-selection of predictors before model building |
| 9b | Methods / Predictors | D;E | Clearly define all predictors, including how and when they were measured (and any actions to blind assessment of predictors for the outcome and other predictors) |
| 9c | Methods / Predictors | D;E | If predictor measurement requires subjective interpretation, describe the qualifications and demographic characteristics of the predictor assessors |
| 10 | Methods / Sample size | D;E | Explain how the study size was arrived at (separately for development and evaluation), and justify that the study size was sufficient to answer the research question. Include details of any sample size calculation |
| 11 | Methods / Missing data | D;E | Describe how missing data were handled. Provide reasons for omitting any data |
| 12a | Methods / Analytical methods | D | Describe how the data were used (eg, for development and evaluation of model performance) in the analysis, including whether the data were partitioned, considering any sample size requirements |
| 12b | Methods / Analytical methods | D | Depending on the type of model, describe how predictors were handled in the analyses (functional form, rescaling, transformation, or any standardisation) |
| 12c | Methods / Analytical methods | D | Specify the type of model, rationale†, all model building steps, including any hyperparameter tuning, and method for internal validation |
| 12d | Methods / Analytical methods | D;E | Describe if and how any heterogeneity in estimates of model parameter values and model performance was handled and quantified across clusters (eg, hospitals, countries). See TRIPOD-Cluster for additional considerations‡ |
| 12e | Methods / Analytical methods | D;E | Specify all measures and plots used (and their rationale) to evaluate model performance (eg, discrimination, calibration, clinical utility) and, if relevant, to compare multiple models |
| 12f | Methods / Analytical methods | E | Describe any model updating (eg, recalibration) arising from the model evaluation, either overall or for particular sociodemographic groups or settings |
| 12g | Methods / Analytical methods | E | For model evaluation, describe how the model predictions were calculated (eg, formula, code, object, application programming interface) |
| 13 | Methods / Class imbalance | D;E | If class imbalance methods were used, state why and how this was done, and any subsequent methods to recalibrate the model or the model predictions |
| 14 | Methods / Fairness | D;E | Describe any approaches that were used to address model fairness and their rationale |
| 15 | Methods / Model output | D | Specify the output of the prediction model (eg, probabilities, classification). Provide details and rationale for any classification and how the thresholds were identified |
| 16 | Methods / Training versus evaluation | D;E | Identify any differences between the development and evaluation data in healthcare setting, eligibility criteria, outcome, and predictors |
| 17 | Methods / Ethical approval | D;E | Name the institutional research board or ethics committee that approved the study and describe the participant informed consent or the ethics committee waiver of informed consent |
| 18a | Open science / Funding | D;E | Give the source of funding and the role of the funders for the present study |
| 18b | Open science / Conflicts of interest | D;E | Declare any conflicts of interest and financial disclosures for all authors |
| 18c | Open science / Protocol | D;E | Indicate where the study protocol can be accessed or state that a protocol was not prepared |
| 18d | Open science / Registration | D;E | Provide registration information for the study, including register name and registration number, or state that the study was not registered |
| 18e | Open science / Data sharing | D;E | Provide details of the availability of the study data |
| 18f | Open science / Code sharing | D;E | Provide details of the availability of the analytical code§ |
| 19 | Patient and public involvement / Patient and public involvement | D;E | Provide details of any patient and public involvement during the design, conduct, reporting, interpretation, or dissemination of the study or state no involvement |
| 20a | Result / Participants | D;E | Describe the flow of participants through the study, including the number of participants with and without the outcome and, if applicable, a summary of the follow-up time. A diagram may be helpful |
| 20b | Result / Participants | D;E | Report the characteristics overall and, where applicable, for each data source or setting, including the key dates, key predictors (including demographics), treatments received, sample size, number of outcome events, follow-up time, and amount of missing data. A table may be helpful. Report any differences across key demographic groups |
| 20c | Result / Participants | E | For model evaluation, show a comparison with the development data of the distribution of important predictors (demographics, predictors, and outcome) |
| 21 | Result / Model development | D;E | Specify the number of participants and outcome events in each analysis (eg, for model development, hyperparameter tuning, model evaluation) |
| 22 | Result / Model specification | D | Provide details of the full prediction model (eg, formula, code, object, application programming interface) to allow predictions in new individuals and to enable third party evaluation and implementation, including any restrictions to access or reuse (eg, freely available, proprietary)¶ |
| 23a | Result / Model performance | D;E | Report model performance estimates with confidence intervals, including for any key subgroups (eg, sociodemographic). Consider plots to aid presentation |
| 23b | Result / Model performance | D;E | If examined, report results of any heterogeneity in model performance across clusters. See TRIPOD-Cluster for additional details‡ |
| 24 | Result / Model updating | E | Report the results from any model updating, including the updated model and subsequent performance |
| 25 | Discussion / Interpretation | D;E | Give an overall interpretation of the main results, including issues of fairness in the context of the objectives and previous studies |
| 26 | Discussion / Limitations | D;E | Discuss any limitations of the study (such as a non-representative sample, sample size, overfitting, missing data) and their effects on any biases, statistical uncertainty, and generalisability |
| 27a | Discussion / Usability of the model in the context of current care | D | Describe how poor quality or unavailable input data (eg, predictor values) should be assessed and handled when implementing the prediction model |
| 27b | Discussion / Usability of the model in the context of current care | D | Specify whether users will be required to interact in the handling of the input data or use of the model, and what level of expertise is required of users |
| 27c | Discussion / Usability of the model in the context of current care | D;E | Discuss any next steps for future research, with a specific view to applicability and generalisability of the model |

### Companion checklist: TRIPOD+AI for Abstracts (Table 3 of the same paper): 13 items
Source footnotes (verbatim): "FOOT: TRIPOD=Transparent Reporting of a multivariable prediction model for Individual Prognosis Or Diagnosis; AI=artificial intelligence.*This checklist is based on the TRIPOD for Abstracts statement published in 2020,17 but has been revised and updated for consistency with the TRIPOD+AI statement.†Relevant only to studies describing the development of a prediction model."

| Item | Section | Item text (verbatim) |
|---|---|---|
| 1 | Title | Identify the study as developing or evaluating the performance of a multivariable prediction model, the target population, and the outcome to be predicted |
| 2 | Background | Provide a brief explanation of the healthcare context and rationale for developing or evaluating the performance of all models |
| 3 | Objectives | Specify the study objectives, including whether the study describes model development, evaluation, or both |
| 4 | Methods | Describe the sources of data |
| 5 | Methods | Describe the eligibility criteria and setting where the data were collected |
| 6 | Methods | Specify the outcome to be predicted by the model, including time horizon of predictions in case of prognostic models |
| 7 | Methods | Specify the type of model, a summary of the model-building steps, and the method for internal validation† |
| 8 | Methods | Specify the measures used to assess model performance (eg, discrimination, calibration, clinical utility) |
| 9 | Results | Report the number of participants and outcome events |
| 10 | Results | Summarise the predictors in the final model† |
| 11 | Results | Report model performance estimates (with confidence intervals) |
| 12 | Discussion | Give an overall interpretation of the main results |
| 13 | Registration | Give the registration number and name of the registry or repository |

### Not verified
- The BMJ web page itself (403). Content verified against the PMC copy only.
- The standalone checklist file from the TRIPOD group and the supplement were not loaded.


## PROBAST+AI

### Citation
Moons KGM, Damen JAA, Kaul T, Hooft L, Andaur Navarro C, Dhiman P, Beam AL, Van Calster B, Celi LA, Denaxas S, Denniston AK, Ghassemi M, Heinze G, Kengne AP, Maier-Hein L, Liu X, Logullo P, McCradden MD, Liu N, Oakden-Rayner L, Singh K, Ting DS, Wynants L, Yang B, Reitsma JB, Riley RD, Collins GS, van Smeden M. PROBAST+AI: an updated quality, risk of bias, and applicability assessment tool for prediction models using regression or artificial intelligence methods. BMJ 2025;388:e082505.
- DOI: 10.1136/bmj-2024-082505 (PMID 40127903, PMCID PMC11931409)
- URLs: https://doi.org/10.1136/bmj-2024-082505 (bmj.com, 403 to bots); loaded: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11931409/fullTextXML (PMC copy, https://pmc.ncbi.nlm.nih.gov/articles/PMC11931409/)
- Checked: 2026-10-14

### Licence
Quoted: "This is an Open Access article distributed in accordance with the Creative Commons Attribution Non Commercial (CC BY-NC 4.0) license, which permits others to distribute, remix, adapt, build upon this work non-commercially, and license their derivative works on different terms, provided the original work is properly cited and the use is non-commercial. See: http://creativecommons.org/licenses/by-nc/4.0/." Copyright line: "Re-use permitted under CC BY-NC. No commercial re-use."

**Reading.** Reproduction with attribution is allowed for non-commercial use only. A public repository is reusable by anyone, including commercial users, and a non-commercial restriction cannot be passed on cleanly through a repository under a permissive licence. I would not copy the question wording verbatim into a public repository without the authors or BMJ confirming this is acceptable. **Unclear for a public, openly licensed repository, so this section is paraphrased.** A short paraphrase with a pointer to the paper is safe.

### Structure (paraphrased: licence does not permit reproduction)
What the paper states (my wording unless marked as quoted):
- Four domains: 1 participants and data sources, 2 predictors, 3 outcomes, 4 analyses. In total 34 signalling questions: 16 for model development and 18 for model evaluation. Plus six applicability items (three each for development and evaluation), covering domains 1 to 3 only.
- Development is judged for **quality** (concern: low, high, unclear). Evaluation is judged for **risk of bias** (low, high, unclear). The paper says this separation is the main change from PROBAST-2019. Bias means systematic error in the estimate of true performance; it is distinct from imprecision.
- Domains 1 to 3 use the same questions (1.1 to 1.3, 2.1 to 2.4, 3.1 to 3.4) in both parts. Domain 4 differs (5 questions for development, 7 for evaluation).
- Answers: yes, probably yes, probably no, no, no information, not applicable. A yes or probably yes always means low concern. A no does not automatically make the whole domain high concern; the assessor judges. "No information" only when reporting is insufficient.
- Four steps: (1) state the purpose of the assessment (PICOTS: population, index model, comparator, outcome, timing, setting and intended use); (2) classify the study as development, evaluation (apparent, internal or external) or both; (3) assess each domain (general information, answer questions, judge the domain, record the rationale); (4) make the overall judgment.
- **Overall judgment (Step 4):** the four domain ratings are combined into an overall rating, low, high or unclear, for quality (development), risk of bias (evaluation) and applicability, separately. Detailed combining rules are in supplementary table 3, which I could not load, so the exact rule is **not verified**. The main text gives one example: an evaluation with no external validation may have domain 4 rated high risk of bias, but if the model was developed on a large dataset with internal validation and the other three domains are low concern, the overall rating may be changed to low risk of bias. A study that only develops a model usually still needs both parts (apparent and internal performance).

#### Model development: signalling questions, one-line paraphrase
| No. | Domain | Paraphrase |
|---|---|---|
| 1.1 | Participants and data sources | Were the data sources appropriate? |
| 1.2 | | Was the study design appropriate? |
| 1.3 | | Did inclusions and exclusions give a representative dataset? |
| 2.1 | Predictors | Were predictors defined and measured the same way in all participants? |
| 2.2 | | Was predictor preprocessing the same for all participants? |
| 2.3 | | Were predictors assessed without knowing the outcome? |
| 2.4 | | Were the predictors available at the time the model is meant to be used? |
| 3.1 | Outcomes | Was the outcome defined and assessed appropriately? |
| 3.2 | | Was the outcome defined and assessed the same way in all participants? |
| 3.3 | | Was the outcome assessed without knowledge of predictor data? |
| 3.4 | | Was the gap between predictor and outcome assessment appropriate? |
| 4.1 | Analyses | Was the sample size reasonable? |
| 4.2 | | Were continuous and categorical predictors handled appropriately? |
| 4.3 | | Were missing or censored data handled appropriately? |
| 4.4 | | If class imbalance was addressed, was the model or its predictions recalibrated? |
| 4.5 | | Were steps taken against overfitting? |

Quality judgments per domain: "concern regarding quality of" selection of participants and data sources, predictors or their assessment, the outcome or its determination, and the analysis. Applicability (domains 1 to 3): concern that the participants' data, the predictor definition, preprocessing, assessment and timing, or the outcome definition, assessment and timing do not match the review question or the assessor's intended use.

#### Model evaluation: signalling questions, one-line paraphrase
Questions 1.1 to 1.3, 2.1 to 2.4 and 3.1 to 3.4 are identical to the development questions above. Domain 4 is:
| No. | Paraphrase |
|---|---|
| 4.1 | Was evaluation based on more than apparent performance alone? |
| 4.2 | Was the sample size reasonable? |
| 4.3 | Were missing or censored data handled appropriately? |
| 4.4 | If class imbalance was addressed, was evaluation done on data without the imbalance correction? |
| 4.5 | If data were split into training and test sets, is there evidence that leakage was avoided? |
| 4.6 | If resampling was used, were all model development steps repeated inside the resampling? |
| 4.7 | Was performance evaluated appropriately (for example calibration, discrimination, net benefit)? |

Risk of bias is judged per domain ("risk of bias introduced by" participant and data source selection, predictors or their assessment, the outcome or its determination, and the analysis), plus the same three applicability concerns.

(Question text above is paraphrased from Table 2 of the paper, loaded 2026-10-14.)

### Not verified
- Supplementary table 3 (full tool and Step 4 combining guidance) and supplementary table 4 (Explanation and Elaboration Light) were not loaded. They are the authoritative place for the overall-judgment rules. Do not fill these in from memory.
- The question wording above is a paraphrase; check the paper for exact wording.

---
## REMARK

### Citations
**(a) 2005 statement.** McShane LM, Altman DG, Sauerbrei W, Taube SE, Gion M, Clark GM; NCI-EORTC Working Group. REporting recommendations for tumour MARKer prognostic studies (REMARK). Br J Cancer 2005;93(4):387-391.
- DOI: 10.1038/sj.bjc.6602678 (PMID 16106245, PMCID PMC2361579)
- URLs: https://doi.org/10.1038/sj.bjc.6602678 (resolves to https://www.nature.com/articles/6602678, HTTP 200); loaded: Europe PMC full text of PMC2361579
- Checked: 2026-10-14

**(b) 2012 explanation and elaboration.** Altman DG, McShane LM, Sauerbrei W, Taube SE. Reporting Recommendations for Tumor Marker Prognostic Studies (REMARK): Explanation and Elaboration. PLoS Med 2012;9(5):e1001216.
- DOI: 10.1371/journal.pmed.1001216 (PMID 22675273, PMCID PMC3362085)
- URLs: https://doi.org/10.1371/journal.pmed.1001216 (resolves to https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1001216, HTTP 200); loaded: https://journals.plos.org/plosone/doi?id=10.1371/journal.pmed.1001216 and Europe PMC full text of PMC3362085
- Checked: 2026-10-14

### Licences
(a) Quoted from the PMC copy: "This article is licensed under a Creative Commons Attribution 4.0 International License, which permits use, sharing, adaptation, distribution and reproduction in any medium or format, as long as you give appropriate credit to the original author(s) and the source, provide a link to the Creative Commons license, and indicate if changes were made." Copyright line: "Copyright © 2005 Cancer Research UK".
(b) Quoted from the PLOS page: "© 2012 Altman et al. This is an open-access article distributed under the terms of the Creative Commons Attribution License, which permits unrestricted use, distribution, and reproduction in any medium, provided the original author and source are credited."

**Reading.** Both permit reproduction in a public repository with attribution. For (a), also link the licence and mark any changes. Note that for (a) I read the CC BY 4.0 statement in the PMC full text; the nature.com page itself I could confirm only as HTTP 200 and did not read its licence block. For (b) the licence is "Creative Commons Attribution License" with no version number in the quoted text.


### Checklist: 20 items, numbered as the source

#### 2012 wording (Altman et al., Table 1), verbatim
| Item | Section | Item text (verbatim) |
|---|---|---|
| 1 | Introduction | State the marker examined, the study objectives, and any pre-specified hypotheses. |
| 2 | Materials and methods / Patients | Describe the characteristics (for example, disease stage or co-morbidities) of the study patients, including their source and inclusion and exclusion criteria. |
| 3 | Materials and methods / Patients | Describe treatments received and how chosen (for example, randomized or rule-based). |
| 4 | Materials and methods / Specimen characteristics | Describe type of biological material used (including control samples) and methods of preservation and storage. |
| 5 | Materials and methods / Assay methods | Specify the assay method used and provide (or reference) a detailed protocol, including specific reagents or kits used, quality control procedures, reproducibility assessments, quantitation methods, and scoring and reporting protocols. Specify whether and how assays were performed blinded to the study endpoint. |
| 6 | Materials and methods / Study design | State the method of case selection, including whether prospective or retrospective and whether stratification or matching (for example, by stage of disease or age) was used. Specify the time period from which cases were taken, the end of the follow-up period, and the median follow-up time. |
| 7 | Materials and methods / Study design | Precisely define all clinical endpoints examined. |
| 8 | Materials and methods / Study design | List all candidate variables initially examined or considered for inclusion in models. |
| 9 | Materials and methods / Study design | Give rationale for sample size; if the study was designed to detect a specified effect size, give the target power and effect size. |
| 10 | Materials and methods / Statistical analysis methods | Specify all statistical methods, including details of any variable selection procedures and other model-building issues, how model assumptions were verified, and how missing data were handled. |
| 11 | Materials and methods / Statistical analysis methods | Clarify how marker values were handled in the analyses; if relevant, describe methods used for cutpoint determination. |
| 12 | Results / Data | Describe the flow of patients through the study, including the number of patients included in each stage of the analysis (a diagram may be helpful) and reasons for dropout. Specifically, both overall and for each subgroup extensively examined report the number of patients and the number of events. |
| 13 | Results / Data | Report distributions of basic demographic characteristics (at least age and sex), standard (disease-specific) prognostic variables, and tumor marker, including numbers of missing values. |
| 14 | Results / Analysis and presentation | Show the relation of the marker to standard prognostic variables. |
| 15 | Results / Analysis and presentation | Present univariable analyses showing the relation between the marker and outcome, with the estimated effect (for example, hazard ratio and survival probability). Preferably provide similar analyses for all other variables being analyzed. For the effect of a tumor marker on a time-to-event outcome, a Kaplan-Meier plot is recommended. |
| 16 | Results / Analysis and presentation | For key multivariable analyses, report estimated effects (for example, hazard ratio) with confidence intervals for the marker and, at least for the final model, all other variables in the model. |
| 17 | Results / Analysis and presentation | Among reported results, provide estimated effects with confidence intervals from an analysis in which the marker and standard prognostic variables are included, regardless of their statistical significance. |
| 18 | Results / Analysis and presentation | If done, report results of further investigations, such as checking assumptions, sensitivity analyses, and internal validation. |
| 19 | Discussion | Interpret the results in the context of the pre-specified hypotheses and other relevant studies; include a discussion of limitations of the study. |
| 20 | Discussion | Discuss implications for future research and clinical value. |


#### Differences in the 2005 wording

The 2005 statement (McShane et al.) has the same 20 items in the same order.
Its wording differs only in spelling ("prespecified", "end point",
"randomised", "tumour", "e.g.") and in item 15, which says "univariate" where
2012 says "univariable"; the 2012 paper footnotes that change as made "for
consistency with 'multivariable'".

### Not verified
- Nature page licence block (page loaded as HTTP 200 only; licence text read from the PMC copy).
- REMARK is for tumour marker prognostic studies; it is not a risk-of-bias tool and has no overall score.

---

## Keeping this file current

The bookworm re-checks each source when a checklist is updated or this file
is a year old, and records the new date. Never fill a gap from memory: the
PROBAST+AI combining rules (its supplementary table 3) are marked not verified
above, and stay so until someone loads that table.
