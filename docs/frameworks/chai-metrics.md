# CHAI metrics

CHAI publishes a consensus set of methods and metrics for each use case, to be
consulted when completing the Applied Model Card. All 279 of them are
reproduced here, and the same list is offered inside the tool at stage 4 when
you record key metrics.

!!! info "Reproduced from CHAI under CC BY 4.0"

    Copyright (c) 2025 Coalition for Health AI, Inc., from
    [responsible-ai-content](https://github.com/coalition-for-health-ai/responsible-ai-content), licensed CC BY 4.0.

    Benchmarks and descriptions are CHAI's own words. Where a metric's
    category differs from CHAI's principle name, it is because this tool
    groups metrics into three categories and CHAI names more; the
    original principle is listed alongside.

## Use cases

| Use case | Metrics | CHAI's framework |
|---|---:|---|
| [Ambient documentation](#ambient-documentation) | 28 | [T&E framework](https://rai-content.chai.org/en/latest/Ambient-AI/t%26e-framework.html) |
| [Agentic AI](#agentic-ai) | 63 | [T&E framework](https://rai-content.chai.org/en/latest/agentic/t%26e-framework.html) |
| [Clinical decision support](#clinical-decision-support) | 9 | [T&E framework](https://rai-content.chai.org/en/latest/clinical-decision-support/t%26e-framework.html) |
| [Clinical trials](#clinical-trials) | 32 | [T&E framework](https://rai-content.chai.org/en/latest/clinical-trials/t%26e-framework.html) |
| [EHR information retrieval](#ehr-information-retrieval) | 9 | [T&E framework](https://rai-content.chai.org/en/latest/electronic-health-record-information-retrieval/t%26e-framework.html) |
| [General health advice chatbot](#general-health-advice-chatbot) | 14 | [T&E framework](https://rai-content.chai.org/en/latest/general-health-advice-chatbot/t%26e-framework.html) |
| [Mental health](#mental-health) | 25 | [T&E framework](https://rai-content.chai.org/en/latest/mental-health/t%26e-framework.html) |
| [Discharge summarization](#discharge-summarization) | 27 | [T&E framework](https://rai-content.chai.org/en/latest/patient-discharge-summarization/te.html) |
| [Prior authorization](#prior-authorization) | 12 | [T&E framework](https://rai-content.chai.org/en/latest/prior-authorization-ai-supported-criteria-matching/t%26e-framework.html) |
| [Sepsis risk prediction](#sepsis-risk-prediction) | 60 | [T&E framework](https://rai-content.chai.org/en/latest/sepsis-risk-prediction/te.html) |

## Ambient documentation

28 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Ambient documentation T&E framework](https://rai-content.chai.org/en/latest/Ambient-AI/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **AI-Generated Documentation Conciseness / Length Change** | Usefulness, usability & efficacy | Usefulness, Usability | Both | Both | External pass/fail threshold not established. Use clinician-written or finalized notes as the local baseline. Report: Length Change = (AI note word count - physician note word count) / physician note word count, plus clinician-rated conciseness. Flag material length increases for qualitative… |
| **Clinician Work Satisfaction Improvement** | Usefulness, usability & efficacy | Usefulness, Usability | Both | Both | Per the Supporting Literature, benchmark as a statistically significant improvement in clinician-reported satisfaction from baseline to post-implementation, measured with a named, validated instrument rather than an ad hoc item. Recommended instruments: the AMA Mini-Z 2.0 satisfaction items or the… |
| **Clinician Preference for AI-Generated Clinical Summaries** | Usefulness, usability & efficacy | Usefulness | Both | Both | Per the Supporting Literature, AI-generated summaries should be preferred by clinicians in >50% of blinded head-to-head comparisons against clinician-written summaries. Report as: Preference Rate = (# AI summaries preferred) / (# total paired comparisons), and report correctness, completeness, and… |
| **Documentation Efficiency Improvement** | Usefulness, usability & efficacy | Usefulness | Both | Both | Per the Supporting Literature, benchmark as approximately >=15% reduction, or >=0.9 minutes saved, in documentation time per appointment relative to pre-deployment baseline across a representative clinician sample. Compute as: ((baseline time - post-deployment time) / baseline time). |
| **Patient-Clinician Engagement Improvement** | Usefulness, usability & efficacy | Usefulness | Both | Both | External pass/fail threshold not established. Use positive change in patient or clinician-reported attention, communication, or engagement as the primary benchmark. As a study-derived reference point, Shah et al. reported 68% positive physician comments for patient engagement, so results near or… |
| **Reduction in Cognitive Task Load (NASA-TLX Change)** | Usefulness, usability & efficacy | Usefulness, Usability, Efficacy | Both | Both | Per the Supporting Literature, benchmark as statistically significant reduction in the NASA-TLX domains used for documentation workload. For operational monitoring, target >=20% relative reduction in the audited workload domain without increased documentation error burden. Compute as: (baseline… |
| **Same-Day Note Closure Rate Increase** | Usefulness, usability & efficacy | Usefulness | Both | Both | Per the Supporting Literature, benchmark as an increase of about >=6 percentage points, or >=9% relative improvement, in same-day note closure compared with baseline. Compute as: post-AI same-day documentation rate - pre-AI same-day documentation rate. |
| **Automatic Speech Recognition (ASR) Demographic Word Error Parity (DWEP)** | Fairness & equity | Fairness, Bias Management | Both | Both | No universal clinical cut point is established. Report max absolute WER gap and WER ratio across demographic subgroups. Use <=0.10 absolute WER gap as a practical remediation trigger for key groups, and require subgroup review when one group has materially higher WER than the best-performing group. |
| **Cross-Demographic Automatic Speech Recognition (ASR) Gender & Accent Error Gap (CDAEG)** | Fairness & equity | Fairness, Bias Management | Both | Both | No universal clinical cut point is established. Report max WER gap across defined gender, dialect, and accent groups. Use <=0.15 max WER gap as a practical internal guardrail, with remediation required when the gap is exceeded or concentrated in a protected or clinically important subgroup.… |
| **Demographic Transcription Equity Rate (DTER)** | Fairness & equity | Fairness, Bias Management | Both | Both | No universal clinical cut point is established. per the Supporting Literature, use DTER >=0.90 as an internal equity guardrail across defined demographic pairs, such as Black vs White speakers or gender groups. Compute as: DTER = min(subgroup transcription accuracy) / max(subgroup transcription… |
| **Contextual and Relationship-Building Omission Rate** | Safety & reliability | Safety, Reliability | Both | Both | No universal benchmark is established. Compute as: (# important contextual elements omitted from AI note) / (# important contextual elements present in transcript or reference documentation). Target a downward trend over time and manually review all omitted contextual elements classified as… |
| **Audio and Transcript Data Retention Control Assessment** | Safety & reliability | Safety, Reliability | Both | Both | No quantitative benchmark is established. Pre-implementation pass condition is documented retention period, deletion process, access control, model-training restriction, patient opt-out or consent workflow, and legal/privacy approval. Because vendor retention practices vary widely and are… |
| **Clinical Summary Completeness and Correctness Non-Inferiority** | Safety & reliability | Safety, Reliability | Both | Both | Per the Supporting Literature, AI-generated summaries should be statistically non-inferior to physician-written summaries on completeness and correctness ratings, using a pre-specified non-inferiority margin. If using a 5-point Likert quality scale, report mean score difference and confidence… |
| **Clinical Note Safety Error Rate (CNSER)** | Safety & reliability | Safety, Reliability | Both | Both | No validated universal threshold is established. Before go-live, notes should be clinician-reviewed and the uncorrected draft error burden should be materially below the simulated-platform reference point of 3.0 moderate-to-severe harm-potential errors per case. Any moderate-to-severe… |
| **Clinically Significant Error Proportion (CSEP)** | Safety & reliability | Safety, Reliability | Both | Both | No validated universal threshold is established. Report the share of notes with at least one clinically significant error and compare against the simulated ambient-scribe reference finding of 26.3% mean key-element error rate. For finalized notes, target zero known clinically significant errors at… |
| **Informed Consent and Documentation Review Compliance Rate** | Safety & reliability | Safety, Reliability | Both | Both | Benchmark as 100% audited compliance for encounters where ambient recording is used: patient notice or consent documented before use, consent exceptions recorded where allowed by policy, and clinician review completed before note finalization. As needed, retain per-encounter evidence… |
| **Usability-Adjusted Safety Reliability Score (UASRS)** | Safety & reliability | Safety, Reliability | Both | Both | UASRS is an internal composite, not an externally validated benchmark. If used, require SUS >=68 or the organization-specific usability target, plus non-worsening after-hours documentation work. Report SUS, after-hours work change, and safety-error measures separately so the composite does not… |
| **Medical Term Recall Rate** | Safety & reliability | Safety | Both | Both | No universal threshold is established. Evaluate against human-annotated clinical transcripts and report recall for diagnoses, medications, procedures, labs, symptoms, and allergies separately. Use >=0.90 as a local pre-deployment target only when annotation quality is high, and escalate any missed… |
| **Clinician Review and Sign-Off Enforcement Rate** | Safety & reliability | Safety | Both | Both | Benchmark as 100% of AI-generated clinical notes requiring clinician review, editing where needed, and sign-off before finalization in the medical record. Verify using workflow configuration and audit logs, and measure the enforcement rate longitudinally (not only at go-live) with per-encounter… |
| **Per-Encounter Control Evidence Retention** | Safety & reliability | Safety, Reliability | Both | Both | No quantitative benchmark established. Pass condition is a retention design under which the listed per-encounter control evidence is captured, tamper-evident, and retrievable for the organization's defined retention window; verify by audit. |
| **LLM Training Data Use Disclosure and Control Assessment** | Safety & reliability | Privacy | Both | Both | No quantitative benchmark is established. Pass condition is written vendor disclosure covering secondary data use, model training, retention, deletion, opt-out or restriction controls, and contract language prohibiting model training on clinical data unless explicitly approved by the deploying… |
| **PHI Redaction / Output Guardrail Verification** | Safety & reliability | Privacy | Both | Both | No universal threshold established. Test against representative samples; report detected PHI-exposure incidents and confirm guardrails were active per encounter where feasible. |
| **Data Residency & Sub-Processor Control** | Safety & reliability | Privacy | Both | Both | No quantitative benchmark. Pass condition is documented data-flow/sub-processor inventory plus audit evidence (logs, attestations, or third-party audit) that data remained within declared boundaries. |
| **Per-Encounter Consent Scope Evidence** | Safety & reliability | Privacy | Both | Both | Recorded encounters have retrievable, per-encounter consent-scope evidence consistent with applicable state all-party consent and CMIA-type requirements. |
| **Incremental Cost-Effectiveness Ratio (ICER), $/QALY** | Usefulness, usability & efficacy | Financial | Both | Both | Benchmark ICER against the organization or payer decision threshold. For US-facing evaluation, $50,000-$150,000 per QALY gained is a common reference range, but it should not be treated as universal. Report all AI implementation, maintenance, monitoring, and clinician review costs used in the… |
| **Weekly Relative Value Units (RVU) Uplift (% change)** | Usefulness, usability & efficacy | Financial | Both | Both | Per the Supporting Literature, benchmark as >=+5.8% weekly RVU increase or about +1.81 RVUs per clinician per week, compared with matched controls or local baseline. Report productivity gains alongside note quality, safety review burden, and clinician workload. |
| **Weekly Encounter Volume Uplift (% change)** | Usefulness, usability & efficacy | Financial | Both | Both | Per the Supporting Literature, benchmark as >=+2.8% encounters per week or about +0.80 encounters per clinician per week, compared with matched controls or local baseline. Interpret as throughput only, not as evidence of improved care quality. |
| **Documentation Time Reduction (minutes/day)** | Usefulness, usability & efficacy | Business | Both | Both | Per the Supporting Literature, benchmark as >=19.95 minutes/day reduction in total EHR time after implementation versus baseline. Report total EHR time, note time, after-hours time, and adoption rate because time savings can vary with use intensity. |

## Agentic AI

63 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Agentic AI T&E framework](https://rai-content.chai.org/en/latest/agentic/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Autonomy Index (AIx)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | No universal AIx threshold is reported in the cited literature. Report the study-defined AIx value by task domain, model architecture, and autonomy level, with unsafe, policy-violating, or incorrectly completed autonomous steps reported separately. |
| **Evaluation Dimension Coverage** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The cited review reports technical metrics in 83% of studies, human-centered assessments in 30%, safety assessments in 53%, economic assessments in 30%, and both technical and human dimensions in 15%. No BECS score or 0-1 threshold is reported. |
| **Goal Completion Rate (GCR)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | AlShikh et al. report an average GCR of 88.8% for the Hybrid Agent in their simulated multi-domain experiment. tau-bench reports that state-of-the-art function calling agents such as gpt-4o succeed on fewer than 50% of tasks and that pass^8 is below 25% in retail. ST-WebAgentBench reports… |
| **Task Success Rate in Multi-Step Clinical Agent Tasks (MedAgentBench)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | MedAgentBench reports 300 patient-specific clinically derived tasks from 10 categories, with Claude 3.5 Sonnet v2 achieving a 69.67% success rate. PhysicianBench reports 100 long-horizon EHR tasks with 670 structured checkpoints, with the best-performing model achieving 46% pass@1 and open-source… |
| **Task Success Rate in WebArena Autonomous Task Benchmark** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | WebArena reports that the best GPT-4-based agent achieved 14.41% end-to-end task success, compared with 78.24% human performance. ST-WebAgentBench evaluates 222 policy-paired tasks and reports Completion under Policy and Risk Ratio rather than a universal 50% target. |
| **User Satisfaction and Human-Centered Feedback Measures** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The cited review reports human-centered assessments in 30% of studies and both technical and human dimensions in 15%. No CSAT >= 80%, NPS, or USS >= 0.8 threshold is reported. |
| **End-to-End Clinical Agent Response Latency (seconds)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | Observed end-to-end response time ranged from 5 to 7 seconds under live deployment conditions. |
| **Triage Appropriateness Rate** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | AI-assisted triage accuracy was 89.3% compared with 74.7% for traditional triage, p < 0.001. |
| **Summarization Editing Effort Reduction** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | LLM-generated hospital course drafts required 31.5% mean editing compared with 44.8% for physician-generated drafts. |
| **Proportion of Errors Auto-Corrected** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | Human experts confirmed 263 of 316 AI Checker-flagged mistakes as actual mistakes, giving 83.2% precision. The AI Checker proposed correct fixes for 75.8% of identified mistakes. |
| **Claim Recall for Summary Factual Coverage** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The study reports TracSum as a benchmark with 500 annotated medical abstracts and 3.5K summary-citation pairs. No universal Claim Recall threshold is reported. |
| **Number of Integrated Wearable / RPM Device Types** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The prototype integrates vital signs, wearable accelerometer data, and visual camera or video data. No minimum device-count threshold is reported. |
| **Per-Record Processing Time (seconds)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | Mean prediction latency was 0.0177 seconds with SD 0.0021, memory utilization was 88.80 MB with SD 0.01, per-record processing time was 0.18 ms, and coefficient of variation was <5%. |
| **Milestone Achievement Rate (Multi-Agent Coordination KPI)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | No universal numeric threshold is reported in the cited source. Use task-defined milestones and report the proportion achieved. |
| **Cost-per-Success (Cost-of-Pass)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The cited Efficient Agents study reports cost-of-pass of $0.228 in its evaluation setting. Outside that setting, establish a local baseline and require cost-per-success to improve without reducing safety, fairness, or policy-compliant task completion. |
| **Slot Extraction F1 Score (SEF1)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | Fine-tuned Llama 3 8B achieved average F1 of 0.77 across the main test datasets and 0.78 when trained with both LLM-generated and human annotations. The study reports a 26 percentage-point absolute F1 increase over vanilla LLMs and a 34% relative F1 improvement over off-the-shelf extractive… |
| **Call Abandonment Rate (CAR)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The supplied citation does not report call abandonment rate or the 5% and 8% thresholds. A different peer-reviewed call-center or healthcare access study is required before using a numeric benchmark. |
| **Top-k Symptom-to-Visit Type Mapping Accuracy (Workflow Gap)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The study reports classification performance for patient self-reported symptom and need text, but it does not define a top-k visit-type benchmark. Use top-k accuracy only against locally annotated scheduling labels; the cited study should be treated as proxy evidence for the text-classification… |
| **Legal Agent Intermediate Progress Rate (LAIPR)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | LegalAgentBench reports 300 annotated tasks spanning 17 legal corpora and 37 tools and computes intermediate progress rate through keyword-based intermediate-step analysis. The cited source reports progress by model and task setting, not a universal deployment threshold. |
| **Patient-Reported Experience Score (Post-Call Voice Survey)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The cited review reports evidence on patient-experience survey administration methods, response rates, and representativeness. It does not report an AI voice-agent top-box threshold or validate a post-call IVR score benchmark. |
| **Provider Preference Match Rate (Workflow Gap)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The cited study supports preference-aware scheduling as an optimization problem. It does not report a fixed provider preference match-rate benchmark. |
| **Cost per Successful Task (CLEAR Framework)** | Usefulness, usability & efficacy | Usefulness, Usability, and Efficacy | Both | Both | The study does not define a fixed numeric cost threshold. It reports up to 50-fold cost variation and that cost-aware alternatives can be 4.4x to 10.8x less expensive than accuracy-only choices under comparable evaluation settings. |
| **Counterfactual Unfairness Level** | Fairness & equity | Fairness and Bias Management | Both | Both | per the Supporting Literature, Counterfactual Unfairness Level <= 0.05. PyCFRL example: baseline policies reported unfairness 0.407 "Full" and 0.446 "Unaware", while the counterfactually fair method achieved 0.042. |
| **Fairness Constraint Evaluation** | Fairness & equity | Fairness and Bias Management | Both | Both | — |
| **Multi-Agent Demographic Parity Fairness Score** | Fairness & equity | Fairness and Bias Management | Both | Both | The cited paper adapts demographic parity, counterfactual fairness, and conditional statistical parity to multi-agent systems. It does not report a universal +/-5% tolerance threshold. |
| **Predictive Parity Ratio** | Fairness & equity | Fairness and Bias Management | Both | Both | No PPR >= 0.9 threshold is reported in the cited article. Report PPV by group and the resulting predictive parity ratio or disparity across prespecified protected attributes. |
| **Human Oversight and Intervention Configuration** | Safety & reliability | Safety and Reliability | Both | Both | — |
| **Policy-Compliant Task Completion Rate (Completion under Policies)** | Safety & reliability | Safety and Reliability | Both | Both | ST-WebAgentBench reports Completion under Policy across 222 tasks and Risk Ratio across safety and trustworthiness dimensions. Report CuP as (# tasks completed with zero policy violations) / (total evaluated tasks), with violations stratified by severity and policy category. |
| **Constraint Violation Rate (CVR)** | Safety & reliability | Safety and Reliability | Both | Both | Li et al. report outcome-driven constraint violation rates ranging from 0.0% to 62.8% across 12 LLMs, with most evaluated models at or above 25%. No universal CVR <= 0.10 threshold is reported. |
| **Safety Risk Category Coverage** | Safety & reliability | Safety and Reliability | Both | Both | No validated HRI >= 0.90 threshold is reported. Agent-SafetyBench evaluates 2,000 test cases across 349 environments, 8 safety-risk categories, and 10 common failure modes. |
| **Safety Score (Agent-SafetyBench)** | Safety & reliability | Safety and Reliability | Both | Both | Agent-SafetyBench contains 2,000 test cases across 349 environments, evaluates 8 categories of safety risks, and covers 10 common failure modes. The study reports that none of the 16 evaluated LLM agents achieved a safety score above 60%, so 60% should not be treated as a target threshold. |
| **Clinical Agent Task Success and Checkpoint Completion** | Safety & reliability | Safety and Reliability | Both | Both | MedAgentBench reports Claude 3.5 Sonnet v2 at 69.67% success on 300 clinically derived EHR tasks. PhysicianBench reports 100 long-horizon EHR tasks with 670 structured checkpoints, with the best model achieving 46% pass@1 and open-source models reaching at most 19%. No TLSCAS >= 0.95 benchmark is… |
| **Plan Adherence Score (PAS)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study reports that Agent GPA identified 95% of human-annotated errors, localized 86% of human-annotated errors, and achieved 76% to 86% error coverage for GPA judges. No PAS >= 0.85 threshold is reported. |
| **Step Correctness Rate (SCR)** | Safety & reliability | Safety and Reliability | Both | Both | AgentProcessBench reports 1,000 trajectories, 8,509 human-labeled step annotations, and 89.1% inter-annotator agreement. No SCR >= 0.80 deployment threshold is reported. |
| **Planning Efficiency Index (PEI)** | Safety & reliability | Safety and Reliability | Both | Both | No verified benchmark could be extracted from the supplied source link. Do not use the PEI >= 0.70 threshold without a supporting study. |
| **Goal Adherence Score (GAS)** | Safety & reliability | Safety and Reliability | Both | Both | The cited report does not define a universal GAS threshold. Report the study-specific goal drift or deviation measure for each agent and task setting. |
| **Intraclass Correlation Coefficient (ICC) for Agent Consistency** | Safety & reliability | Safety and Reliability | Both | Both | The cited study proposes ICC for agentic evaluation reliability. No universal ICC >= 0.70 or ICC >= 0.80 threshold for agent deployment is reported. |
| **Standard Deviation of Task Success Rate (SD-TSR)** | Safety & reliability | Safety and Reliability | Both | Both | The study reports that single-run pass@1 estimates vary by 2.2 to 6.0 percentage points depending on the selected run, with standard deviations exceeding 1.5 percentage points even at temperature 0. No universal SD-TSR pass/fail threshold is reported. |
| **Tool Selection Accuracy (TSA)** | Safety & reliability | Safety and Reliability | Both | Both | MCPAgentBench introduces authentic tasks, simulated MCP tools, distractor tool lists, task completion rates, and execution efficiency metrics. No universal TSA >= 0.80 threshold is reported. |
| **Tool Invocation Correctness (TIC)** | Safety & reliability | Safety and Reliability | Both | Both | BFCL evaluates serial and parallel function calls across programming languages using AST-based evaluation. No universal TIC >= 0.85 threshold is reported. |
| **TESR (Tool Execution Success Rate)** | Safety & reliability | Safety and Reliability | Both | Both | FinToolBench reports 760 executable financial tools and 295 tool-required queries. No universal TESR >= 0.90 threshold is reported. |
| **Task Completion Rate with Tool Use (TCR-T)** | Safety & reliability | Safety and Reliability | Both | Both | The cited survey does not report a universal TCR-T threshold. Use benchmark-specific task completion rate definitions and report tool-use failures separately. |
| **Noise-Induced Performance Degradation (NIPD)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study introduces AgentNoiseBench for noisy-condition evaluation. No universal <=10 percentage point degradation threshold is reported in the source metadata. |
| **Pass@1 Task Completion Rate** | Safety & reliability | Safety and Reliability | Both | Both | APEX-SWE includes 100 integration tasks and 100 observability tasks. The supplied citation does not support using pass@1 >= 0.40 as a general benchmark for non-software domains. |
| **Epistemic Verification Behavior Rate** | Safety & reliability | Safety and Reliability | Both | Both | No standardized threshold is reported in the cited source. Report verification behaviors using task-specific annotation criteria if used. |
| **Decision Accuracy Under Incomplete Information** | Safety & reliability | Safety and Reliability | Both | Both | Finance Agent Benchmark reports 537 expert-authored questions across nine financial task categories. No universal accuracy threshold is reported. |
| **Escalation Rate (ESR)** | Safety & reliability | Safety and Reliability | Both | Both | tau-bench reports that state-of-the-art agents still fail more than 50% of tasks in some customer-service domains and that pass^8 can drop below 25% in the retail setting. The study does not report an escalation-rate threshold for healthcare voice scheduling. |
| **Platform Reliability Score (PRS)** | Safety & reliability | Safety and Reliability | Both | Both | Larsen et al. analyzed 80,381 patient safety event reports and identified 76 events associated with healthcare IT downtime. The cited sources do not report an AI voice-agent platform reliability score or validate a 99.9% uptime threshold. |
| **Real-Time Oversight Layer / Independent Output Monitoring Rate (Guard Rail)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study supports measuring oversight error detection through sensitivity and response bias. It does not report a 100% monitoring coverage benchmark for healthcare voice agents. |
| **Hard Turn Limit Compliance Rate (Guard Rail)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study reports degradation when models must use information located in the middle of long contexts. It does not report a 15 to 20 turn ceiling or a 100% compliance benchmark. |
| **Output Constraint Violation Rate (Guard Rail)** | Safety & reliability | Safety and Reliability | Both | Both | CONFAIDE reports that GPT-4 and ChatGPT reveal private information in 39% and 57% of evaluated cases, respectively. The study does not report a healthcare voice-scheduling constraint-violation threshold or validate a 0% benchmark. |
| **Node-Level Regression Test Coverage Rate (Guard Rail)** | Safety & reliability | Safety and Reliability | Both | Both | The cited source supports evaluation-driven lifecycle testing for agentic AI systems. It does not report a 100% node coverage benchmark or a healthcare voice-scheduling threshold. |
| **End-to-End Trace Coverage Rate (Guard Rail)** | Safety & reliability | Safety and Reliability | Both | Both | The cited source supports observability and tracing for LLM-agent systems. It does not report a 100% trace-coverage benchmark or a HIPAA retention benchmark. |
| **Pass@k Reliability for Agentic Financial Tasks** | Safety & reliability | Safety and Reliability | Both | Both | CLEAR reports that single-run reliability of 60% can drop to 25% under 8-run consistency and documents large cost differences across systems. It does not report pass@5 greater than or equal to 0.90 as a validated threshold. |
| **Intermediate Step Correctness Rate** | Safety & reliability | Safety and Reliability | Both | Both | The cited study reports intermediate progress tracking for legal-agent tasks, but it does not define a correctness-based threshold. |
| **Decontaminated Task Success Rate** | Safety & reliability | Safety and Reliability | Both | Both | The supplied source does not provide a verified peer-reviewed benchmark. Use only after replacing the citation with a verifiable paper that reports decontaminated task success results. |
| **Cumulative Risk Exposure (Multi-Agent System Safety Metric)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study defines and demonstrates cumulative risk exposure but does not report a universal numeric safety threshold. Lower cumulative risk exposure is used for comparative evaluation. |
| **Regression Non-Introduction Rate (RNIR)** | Safety & reliability | Safety and Reliability | Both | Both | SWE-bench contains 2,294 real GitHub issues and reports Claude 2 resolving 1.96% in the original evaluation. The cited paper does not report a 500-instance SWE-bench Verified threshold or a 70% resolve-rate benchmark. |
| **Business Policy Adherence Rate (BPAR)** | Safety & reliability | Safety and Reliability | Both | Both | tau-bench evaluates retail, airline, and telecom tasks with domain-specific policies and annotated goal states. The paper reports that state-of-the-art agents can achieve less than 50% pass^1 in the retail domain and pass^8 below 25%; it does not report a universal BPAR threshold. |
| **PPE Non-Compliance Alert Precision-Recall F1 (PNA-F1)** | Safety & reliability | Safety and Reliability | Both | Both | The cited study reports PPE detection mAP@50 of 83.1% for a YOLOv5 hybrid dataset and reports model-specific precision, recall, and F1 values in construction footage experiments. It does not validate a universal PNA-F1 greater than or equal to 0.90 deployment threshold. |
| **Errors-of-Omission Rate** | Safety & reliability | Safety and Reliability | Both | Both | — |
| **Automation Bias / Overreliance** | Safety & reliability | Safety and Reliability | Both | Both | — |
| **Economically Valuable Administrative Task Success Rate (HealthAdminBench)** | Usefulness, usability & efficacy | Business and Financial | Both | Both | HealthAdminBench reports 135 expert-defined tasks and 1,698 evaluation points across four simulated administrative environments, evaluating seven agent configurations. The best-performing agent (Claude Opus 4.6 CUA) reached 36.3% end-to-end task success, while GPT-5.4 CUA reached the highest… |

## Clinical decision support

9 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Clinical decision support T&E framework](https://rai-content.chai.org/en/latest/clinical-decision-support/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Task Completion Time** | Usefulness, usability & efficacy | Usability | Post-Implementation | Implementer | — |
| **Evidence Concordance, Citation Accuracy, and Guideline Alignment** | Usefulness, usability & efficacy | Efficacy | Pre-Implementation | Both | Suggested benchmarks include: ≥ 90% evidence concordance with specialty guidelines, 100% verifiable citations, <5% hallucinations in reference-linked outputs. |
| **Detection Accuracy** | Usefulness, usability & efficacy | Efficacy | Both | Both | Hybrid AI workflows that combine LLM-based generation with domain-specific retrieval and expert validation typically achieve higher detection accuracy---including improved F1-score and recall for clinically significant events---compared to LLM-only approaches, with minimal loss in precision. |
| **Hallucination Rate and Response Time** | Usefulness, usability & efficacy | Efficacy | Both | Both | Suggested that AI-enabled CDS achieve near-zero hallucination rates, high factual accuracy (organizational dependent), and significantly faster response times than traditional human review---demonstrating strong reliability and operational efficiency in CDS contexts. |
| **Stratified Subgroup Performance** | Fairness & equity | Fairness | Both | Both | — |
| **Subgroup Accuracy Across Sensitive Attributes** | Fairness & equity | Fairness | Pre-Implementation | Both | — |
| **Cross-Site Generalizability and Calibration Gap** | Fairness & equity | Bias Management | Both | Both | No universal threshold established. Aim for minimal performance degradation (e.g., ≤5--10% difference in accuracy or calibration slope) when evaluated across sites or demographic groups; Significant deviation should prompt bias investigation and potential retraining. |
| **Safety-related Overrides** | Safety & reliability | Safety | Post-Implementation | Both | — |
| **Stress and Adversarial Scenario Evaluation** | Safety & reliability | Safety, Reliability | Both | Implementer | — |

## Clinical trials

32 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Clinical trials T&E framework](https://rai-content.chai.org/en/latest/clinical-trials/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Eligibility Improvement & Enrollment Uptake** | Usefulness, usability & efficacy | Usefulness, Efficacy | Both | Both | per the Supporting Literature, >95% exclusion reduction from ML+abstraction over structured alone; 17% of surfaced patients consented in 10 days. |
| **Enrollment Rate** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, enrollment increase by 11.1%; screening time decrease by 34%; SUS usability score = 80 |
| **Patient-Criterion Fairness-Constrained Matching (Accuracy/F1/DP/EO)** | Fairness & equity | Fairness and Bias Management | Both | Both | per the Supporting Literature, reported metrics include accuracy, F1, demographic parity, and equalized odds across patient-criterion and patient-trial matching tasks; FairPM reduced group disparity with limited performance tradeoff. |
| **Prognostic Covariate-Adjusted Mixed Models for Repeated Measures (PROCOVA-MMRM)** | Usefulness, usability & efficacy | Usefulness | Both | Both | per the Supporting Literature, Alzheimer's trial estimated sample size reduction was 7.1% for ADAS-Cog11 and 13.0% for CDR-SB; ALS trial estimated sample size reduction was 15.3%, with lower endpoint treatment-effect variance versus unadjusted MMRM. |
| **Relevance Explanation & Evidence Accuracy** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, 87.8% correct explanations; F1 = 88.6% for evidence retrieval |
| **Screening & Abstraction Efficiency: Abstraction Time, EHR Alerts** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, Abstraction median = 13.3 hrs (priority 3.0–9.9 hrs); EHR-integrated alerting system |
| **Screening & Abstraction Efficiency: Screening Time Reduction** | Usefulness, usability & efficacy | Usefulness | Both | Both | per the Supporting Literature, 42.6% avg time reduction across 36 patient-trial cases. |
| **Screening Efficiency: Funnel yield, Review time** | Usefulness, usability & efficacy | Efficacy | Both | Both | per the Supporting Literature, structured exclusions: ~99%; final eligibility yield: 3.0% / 4.0%; 13.3 hr median |
| **Sensitivity/Specificity (with Probability Calibration)** | Usefulness, usability & efficacy | Efficacy | Both | Both | per the Supporting Literature, meta-analysis (oncology, auto-matching): pooled sensitivity ≈ 90.5%, specificity ≈ 99.3% (retrospective); prospective/pragmatic eval (4 tools, 3,800 patients): mean sensitivity ≈ 0.32 (illustrates real-world degradation vs. retrospective results; motivates… |
| **System Explainability Scale (SES)** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, clinician scores: Usability = 4.71, Trust = 4.53, Understandability = 4.51 (out of 5); SES reliability: Cronbach’s alpha of 0.84; Spearman’s rho of 0.81. |
| **Trial Matching & Ranking Evaluation: Accuracy (NDCG@10, AUROC, Accuracy)** | Usefulness, usability & efficacy | Efficacy | Both | Both | per the Supporting Literature, Accuracy = 87.3% (expert range of 88.7–90.0%); AUROC = 0.7979 (vs. baseline of 0.6176) |
| **Trial Matching & Ranking Evaluation: Match Accuracy** | Usefulness, usability & efficacy | Usefulness | Both | Both | per the Supporting Literature, 45.7% of returned trials were valid matches; 91% increase in match rate when expanding radius to 20 miles. |
| **Trial Matching & Ranking Evaluation: Matching Accuracy & Ranking Quality** | Usefulness, usability & efficacy | Usefulness, Efficacy | Both | Both | per the Supporting Literature, mean precision = 0.33, mean sensitivity = 0.32, AP@3 = 0.45, and NDCG@3 = 0.34 across the four evaluated trial-matching tools; Klineo achieved mean precision = 0.52 and sensitivity = 0.50. |
| **Trial Matching & Ranking Evaluation: Matching Concordance & Speed** | Usefulness, usability & efficacy | Usefulness, Efficacy | Both | Both | per the Supporting Literature, 97.9% concordance; 0.04s median match time; zero false positives |
| **Generated Narrative Quality (PDSQI-9)** | Usefulness, usability & efficacy | Usefulness, Usability | Both | Both | per the Supporitng Literature, PDSQI-9 was validated on clinical note / discharge summarization, not on trial-eligibility rationale or patient-facing trial summaries. Reported source-study scores and inter-rater reliability are observed values in that context and should be re-baselined locally. |
| **AEq (Accessibility Equity)** | Fairness & equity | Bias Management | Both | Both | per the Supporting Literature, Chest X-rays: AEq gap between White and Black patient groups reduced from 0.25 to 0.05 after mitigation. |
| **Fairness via Equalized Odds** | Fairness & equity | Fairness and Bias Management | Both | Both | per the Supporting Literature, FairPM achieved significantly lower disparity (demographic parity and equalized odds) with minimal performance drop: Patient-criterion: Accuracy ≈ 0.913, F1 ≈ 0.936 (vs baseline 0.959/0.970); Patient-trial: Accuracy ≈ 0.801–0.833, F1 ≈ 0.889–0.909 with DP ≈… |
| **Patient-Trial Fairness Gap (Demographic Parity/Equalized Odds)** | Fairness & equity | Fairness and Bias Management | Both | Both | per the Supporting Literature, FairPM reported reduced demographic parity and equalized odds gaps on patient-trial matching while maintaining trial-level accuracy and F1 within the reported performance range. |
| **Representativeness Ratio** | Fairness & equity | Fairness | Both | Both | per the Supporting Literature, Direct-to-Participant recruitment: 27.8% rural vs. site-based: 13.5% rural; rural Direct-to-Participant participants: 12.5% Black vs. 9.6% site-based. |
| **Deployment & Structured Output Capability (via GPT-OSS)** | Safety & reliability | Reliability | Both | Both | Infrastructure capability benchmark; per the Supporting Literature, gpt-oss supports structured outputs and function calling for developer workflows. |
| **Failure Mode Analysis (Qualitative Adverse Event & Bias Review)** | Safety & reliability | Safety / Reliability | Both | Both | Qualitative framework; no quantitative benchmark reported in the Supporting Literature |
| **Failure Mode Taxonomy & Mitigation Strategies** | Safety & reliability | Safety / Reliability | Both | Both | Qualitative framework; no quantitative benchmark reported in the Supporting Literature |
| **Mean Time Between Failures (MTBF) + Failure Rate Framework** | Safety & reliability | Reliability | Both | Both | Deployment-specific metric; compute MTBF as total uptime divided by number of failures and failure rate as failures per operating time using production system logs. |
| **Observed Detection Rate per 1,000** | Safety & reliability | Safety / Reliability | Both | Both | per the Supporting Literature, Ductal Carcinoma in Situ (DCIS): 1.4 vs 0.8 per 1,000; Invasive: 5.2 vs 4.8 per 1,000 (AI vs baseline) |
| **Predictive Reliability** | Safety & reliability | Reliability | Both | Both | per the Supporting Literature, Simulation: AUC 0.87 vs 0.71 (reliable vs unreliable cases); Real-world MS dataset: predictive reliability successfully separated low- vs high-confidence predictions (validated in relAI package). |
| **QUEST Human Evaluation Framework: 5 scoring domains – Quality, Understanding & Reasoning, Expression, Safety, Trust** | Safety & reliability | Safety / Reliability | Both | Both | Qualitative framework; no quantitative benchmark reported in the Supporting Literature |
| **Recall@3 (Human-in-the-Loop)** | Safety & reliability | Safety | Both | Both | Recall@3 (Human-in-the-Loop, HITL): per the Supporting Literature, 67.3%; Recall@1 (HITL): 55.4%; Recall@5 (HITL): 77.9%. |
| **AI-Assisted Data Cleaning Cost Savings** | Usefulness, usability & efficacy | Financial | Both | Both | — |
| **AI-Assisted Prescreening Cost per Patient-Trial Pair** | Usefulness, usability & efficacy | Financial | Both | Both | — |
| **Database Lock Timeline and Data Cleaning Cost Reduction** | Usefulness, usability & efficacy | Financial | Both | Both | — |
| **Screening Labor Cost Avoidance: Ineligible Chart Review Reduction** | Usefulness, usability & efficacy | Financial | Both | Both | — |
| **Energy Consumption Index** | Usefulness, usability & efficacy | Energy | Both | Both | per the Supporting Literature, CodeCarbon-estimated training energy on TITAN Xp was approximately ResNet18 = 0.1155 kWh and EfficientNet-B3 = 0.1160 kWh. |

## EHR information retrieval

9 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's EHR information retrieval T&E framework](https://rai-content.chai.org/en/latest/electronic-health-record-information-retrieval/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Accuracy -- Document Extraction** | Usefulness, usability & efficacy | Usefulness, Efficacy | Pre-Implementation | Developer | — |
| **Accuracy -- Data Mapping** | Usefulness, usability & efficacy | Usefulness, Efficacy | Pre-Implementation | Developer | Data mapping accuracy typically varies across structured data elements, with high performance on simpler elements (e.g., coded medication fields) and lower performance on more complex temporal or contextual attributes (e.g., dosage timing, medication form). Published results show F1-scores ranging… |
| **Deterministic Reproducibility of LLM Inference** | Usefulness, usability & efficacy | Efficacy | Both | Both | Suggested benchmark (per cited study): Output stability >99% exact-match rate across 100 repeated inference runs with fixed seeds and identical input prompts; semantic variability <1% using embedding-based similarity metrics (cosine > 0.99). |
| **Demographic Parity Ratio + Equality of Opportunity Difference** | Fairness & equity | Fairness | Pre-Implementation | Both | — |
| **Structural Missingness Disparity Assessment** | Fairness & equity | Bias Management | Pre-Implementation | Developer | Supporting literature demonstrates that demographic subgroups often show large disparities in measurement frequency (e.g., vital sign monitoring), and that missingness patterns alone can significantly predict outcomes (e.g., mortality AUC ≈ 0.76 in ICU populations). |
| **Incidence of Reporting Errors Before and After Standardization** | Safety & reliability | Safety | Both | Implementer | — |
| **Inter-rater Reliability (IRR)** | Safety & reliability | Safety | Pre-Implementation | Developer | — |
| **Error Rate** | Safety & reliability | Safety, Reliability | Post-Implementation | Both | — |
| **Correctness & Completeness** | Safety & reliability | Safety, Reliability | Both | Both | — |

## General health advice chatbot

14 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's General health advice chatbot T&E framework](https://rai-content.chai.org/en/latest/general-health-advice-chatbot/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **A/B Preference Agreement Rate; Alignment Score with Reference Answers; Open-Forum Response Usefulness Score** | Usefulness, usability & efficacy | Usefulness | Both | Developer: use for tuning… | >70% A/B Preference Agreement with higher-quality variant; ≥85% Alignment with Reference Answers; actionable feedback collected across diverse user groups |
| **Crash Rate, Error Rate (per session); Failure-to-Progress Rate; Session Abandonment Rate** | Usefulness, usability & efficacy | Usability | Both | Developer: use to debug and… | <1% of sessions with crashes, malformed responses, or unresolved rephrasing attempts |
| **C-SAT Score (Mean/Median)** | Usefulness, usability & efficacy | Usability | Post-Implementation | Implementer: captures… | ≥4.2 Mean C-SAT; monitor trends over time for degradation or improvement |
| **Percentage (%) Uptime** | Usefulness, usability & efficacy | Efficacy | Post-Implementation | Implementer: tracks system… | ≥99.5% uptime over a given evaluation period (e.g., monthly) |
| **Cache Hit Rate; Intent Mapping Accuracy; Response Time Reduction; LLM Call Reduction Rate** | Usefulness, usability & efficacy | Efficacy | Both | Developer: optimize model… | >60% Cache Hit Rate; Measurable improvement in response time (≥30% reduction); >90% Intent Mapping Accuracy |
| **Low-Confidence Trigger Rate; Escalation Success Rate** | Usefulness, usability & efficacy | Efficacy | Both | Developer: refine fallback… | <5% Low-Confidence Trigger Rate; >90% Escalation Success Rate |
| **Toxicity Rate; Bias Detection Rate** | Fairness & equity | Fairness | Both | Developer: implement… | <0.01% of conversations with toxic, biased, or unfair content |
| **Expected Calibration Error (ECE) - stratified by subgroup** | Fairness & equity | Fairness | Both | Developer: evaluate and… | ECE < 5% overall; subgroup ECE parity (≤2% variation across groups) |
| **Intersectional Fairness Score** | Fairness & equity | Fairness | Both | Developer: detect and… | Intersectional Fairness Score ≥ 0.90 across key subgroups; no subgroup >10% below group average |
| **Bias-Induced Divergence Rate; Group Fairness Gap** | Fairness & equity | Bias Management: Anti-classification | Both | Developer: detect and… | Bias-Induced Divergence Rate <1%; Group Fairness Gap ≤0.2 on 1--5 response quality scale |
| **Mean Response Quality Score by Group; Disparity Index** | Fairness & equity | Bias Management: General Bias | Both | Developer: assess and… | Disparity Index ≤ 0.5 on 1--5 quality scale; Mean score ≥4.0 across all groups |
| **F1 Score (with Precision and Recall) - stratified F1 Score by subgroup** | Fairness & equity | Bias Management: Parity | Both | Developer: measure and… | F1 ≥ 0.85 overall; ≤ 0.05 variation in F1 between subgroups |
| **Unsafe Conversation Rate** | Safety & reliability | Safety | Both | Developer: improve safety… | <0.01% of conversations flagged as unsafe |
| **Self-Reported Adverse Experience Rate** | Safety & reliability | Safety | Post-Implementation | Implementer: capture… | <1% of users report an adverse experience during a defined timeframe |

## Mental health

25 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Mental health T&E framework](https://rai-content.chai.org/en/latest/mental-health/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Cognitive Behavioral Therapy (CBT) Technique Adherence Score (CTAS)** | Usefulness, usability & efficacy | Usefulness | Both | Both | per the Supporting Literature, use an expert-validated benchmark set with ideal responses and a pre-specified 0 to 5 CBT-adherence rubric. No universal pass threshold is reported; compare against baseline model performance and review low agreement with ideal responses or expert ratings. |
| **Chatbot Usability Questionnaire Score (CUQS)** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, use the 0 to 100 normalized usability score as a product trend metric. Set the initial benchmark from pre-release usability testing, compare each release against that baseline, and review any material decline in overall score or core usability dimensions such as ease… |
| **Clinical Response/Remission Rate (CRRR)** | Usefulness, usability & efficacy | Efficacy | Both | Both | per the Supporting Literature, use the reported 4-week and 8-week symptom-change outcomes and effect-size ranges for MDD, GAD, and CHR-FED as contextual comparators. Use response or remission rates only when the evaluated study pre-specifies those endpoints, and review materially weaker outcomes… |
| **Interface Mode Preference & Satisfaction Score (IMPS)** | Usefulness, usability & efficacy | Usability | Both | Both | per the Supporting Literature, compare interface modes using System Usability Scale reference values reported in the trial, text-only chatbot mean 75.34 vs digital human mean 64.80. No universal IMPS threshold is reported; use the study values as a contextual comparator and investigate sustained… |
| **Symptom Reduction Effect Size Score (SRES)** | Usefulness, usability & efficacy | Efficacy | Both | Both | per the Supporting Literature, use Hedges' g=0.64 for depression symptoms and g=0.70 for distress as contextual reference points for AI-based conversational agents. No significant pooled effect was found for overall psychological well-being, so require separate outcome-specific benchmarks. |
| **Cross-Demographic Safety & Quality Disparity Score (CDSQ-DS)** | Fairness & equity | Fairness, Bias Management | Both | Both | No universal numeric benchmark is reported. Use group-wise performance and fairness gaps across protected social factors as the benchmark; target near-zero systematic disparity and trigger review when any group shows consistent safety or quality degradation across datasets or prompt settings. |
| **Evaluation Bias Rate (GSEBR)** | Fairness & equity | Fairness, Bias Management | Both | Both | per the Supporting Literature, benchmark by within-vignette score divergence across gender and sexual-orientation variants; target no statistically significant demographic effect. Trigger review for effects like the reported ChatGPT-4 RAND-36 mental composite gender difference, male case mean 12.8… |
| **Race-Condition Bias Score (RCBS) for Diagnosis & Treatment** | Fairness & equity | Fairness, Bias Management | Both | Both | per the Supporting Literature, score race-conditioned outputs 0 to 3 against race-neutral outputs, where 0 means minimal difference, 2 means significant race-attributable difference, and 3 means racist response. Target mean bias score near 0 and no case-level diagnosis or treatment score of 2 or… |
| **Adherence to Practice Guidelines Score** | Safety & reliability | Safety | Both | Both | per the Supporting Literature, score responses against the five guideline questions and ideal responses on a 1 to 10 expert-rating scale. No universal pass threshold is reported, so pre-specify the operating threshold and review responses with low guideline adherence or large deviation from expert… |
| **Consistency in Critical Scenarios (Variance across Semantically Similar Prompts)** | Safety & reliability | Safety, Reliability | Both | Both | No universal numeric threshold is reported. Benchmark by repeated responses to semantically similar high-risk prompts and review materially different safety guidance, risk handling, or resource provision against ideal responses. |
| **Expert Safety Score (ESS)** | Safety & reliability | Safety | Both | Both | per the Supporting Literature, aggregate expert ratings across the five guideline dimensions on a 1 to 10 scale using the 100-question benchmark and ideal responses. No universal threshold is reported, so use a pre-specified internal threshold and review low-scoring dimensions. |
| **VERA-MH (Spring Health)** | Safety & reliability | Safety, Transparency; cross-cutting for evaluation | Both | Both | Scores commercially available chatbots 0–100 on each of the five dimensions plus an overall safety score. The v1 leaderboard shows meaningful variation across models — notably, most models score high on detecting potential risk but markedly lower on guiding to human care and confirming risk —… |
| **Cost Savings per Participant in Guided Internet-Delivered CBT vs In-Person Therapy ($)** | Usefulness, usability & efficacy | Financial | Both | Both | per the Supporting Literature, use the reported first-step intervention cost benchmark, $2,140 per participant for guided internet-delivered CBT versus $4,244 for in-person CBT, a $2,104 lower cost. Treat as contextual cost benchmark, not a universal savings target for genAI wellness applications. |
| **Cost per Quality-Adjusted Life Year (QALY) for Digital Mental Well-Being Tools** | Usefulness, usability & efficacy | Financial | Both | Both | per the Supporting Literature, use the review's reported range as a contextual benchmark, dominant to €18,710, US $23,185, per QALY. Compare only when the product has measured costs, QALYs, and a defined comparator; do not infer QALY value from engagement or satisfaction alone. |
| **Incremental Cost-Effectiveness Ratio (ICER) per QALY for AI-Assisted CBT** | Usefulness, usability & efficacy | Financial | Both | Both | per the Supporting Literature, benchmark against ICER $37,295 per QALY and $3,623 per treatment success, with 89.4% probability of cost-effectiveness at $50,000/QALY. Apply only when comparable clinical outcome and cost data exist for the evaluated product. |
| **Framework for AI Tool Assessment in Mental Health (FAITA-Mental Health)** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | per the Supporting Literature, ordinal subdomain scoring uses 0 to 2 descriptive anchors with a total range of 0 to 24. No prescriptive numeric threshold for passing is specified; use domain-level scores for cross-tool comparison and to identify weak readiness areas. |
| **Readiness Evaluation for AI-Mental Health Deployment and Implementation (READI) Framework** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | per the Supporting Literature, the framework provides component-level evaluation criteria, evaluation questions, and proposed reporting requirements rather than a numeric scoring system or single readiness threshold. Use component-level gaps and use-case risk as the benchmark; do not collapse… |
| **MindEval Framework (Sword Health)** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | per the Supporting Literature, each criterion is scored 1 to 6, with 1 to 2 indicating serious problems, 3 to 4 acceptable to solid performance, and 5 to 6 exceptional performance. Published model averages ranged from 2.16 to 3.83 and no model exceeded 4.0; use 4.0 as a practical review threshold… |
| **MindBench.ai Platform** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | per the Supporting Literature, profile items are binary or numeric and performance benchmarks use expert-rated SIRI-2 style scores from -3 to +3 with means and standard deviations. No composite score is intended; benchmark at the domain level using crisis response, clinical-case performance,… |
| **Verily Behavioral Health Safety Filter (VBHSF) and Verily Mental Health Crisis Dataset v1.0 (Verily)** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | per the Supporting Literature, internal evaluation sensitivity was 0.990, specificity was 0.992, and macro F1 was 0.939; external evaluation sensitivity was 0.982 and specificity was 0.859. Prioritize crisis sensitivity and set alerting thresholds so missed-crisis risk remains below the reference… |
| **Responsible Evaluation of AI for Mental Health (interdisciplinary evaluation taxonomy)** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | Not a scoring system. Use the taxonomy as a coverage benchmark: assessment tools should show convergent and discriminant validity; intervention tools should show benefit, safety, and acceptability; information-synthesis tools should show workflow or decision-quality improvements. Use it to check… |
| **CRADLE Bench** | Safety & reliability | Safety (crisis detection); cross-cutting for evaluation | Both | Both | 600 clinician-annotated eval + 420 dev + ~4K ensemble-labeled training examples; seven clinically defined crisis types; first to include temporal labels; six fine-tuned detectors under consensus/unanimous agreement. (Per-type detection metrics are reported in the paper tables — pull specific… |
| **Counsel Bench** | Usefulness, usability & efficacy | Usefulness, Safety, Transparency | Both | Both | 100 real questions × 20 topics; 2,000 expert evaluations (5 raters each; Krippendorff's α 0.72–0.83); 120 adversarial questions; six evaluation dimensions; symptom-speculation failure triggered in ~67–87% of model responses; LLM-as-judge shown to inflate scores and rarely flag flagged spans.… |
| **EPITOME Framework** | Usefulness, usability & efficacy | Usefulness (empathy/quality of support); Transparency… | Both | Both | Three empathy mechanisms (emotional reactions, interpretations, explorations), each with communication levels; 10k rationale-annotated (post, response) pairs; multi-task RoBERTa bi-encoder for empathy identification + rationale extraction; large-scale application to 235k interactions. See F1… |
| **Human Agency Preservation and Dependency-Risk Evaluation** | Usefulness, usability & efficacy | Cross-Cutting | Both | Both | — |

## Discharge summarization

27 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Discharge summarization T&E framework](https://rai-content.chai.org/en/latest/patient-discharge-summarization/te.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **DocLens** | Usefulness, usability & efficacy | — | Both | Both | — |
| **ROUGE (Recall-Oriented Understudy for Gisting Evaluation)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **BERTScore** | Usefulness, usability & efficacy | — | Both | Both | — |
| **MoverScore** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Sentence Mover's Similarity** | Usefulness, usability & efficacy | — | Both | Both | — |
| **SummaQA** | Usefulness, usability & efficacy | — | Both | Both | — |
| **BLANC** | Usefulness, usability & efficacy | — | Both | Both | — |
| **SUPERT** | Usefulness, usability & efficacy | — | Both | Both | — |
| **BARTScore** | Usefulness, usability & efficacy | — | Both | Both | — |
| **ACUEval** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Bilingual Evaluation Understudy (BLEU)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **METEOR** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Counterfactual DocLens** | Fairness & equity | — | Both | Both | — |
| **Counterfactual Sentiment Parity** | Fairness & equity | — | Both | Both | — |
| **Expected Maximum Toxicity** | Safety & reliability | — | Both | Both | — |
| **Reliability of DocLens** | Safety & reliability | — | Both | Both | — |
| **Toxic Fraction** | Safety & reliability | — | Both | Both | — |
| **Toxicity Probability** | Safety & reliability | — | Both | Both | — |
| **Holistic Evaluation of Language Models (HELM)** | Safety & reliability | — | Both | Both | — |
| **Medsafetybench** | Safety & reliability | — | Both | Both | — |
| **Calibration** | Safety & reliability | — | Both | Both | — |
| **Proportion of Uses Disclosed to Patients** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Availability of AI System Facts** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Clinical-Grade Evaluation of Large Language Models** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Model Uptime/Failed Generations when Deployed** | Safety & reliability | — | Both | Both | — |
| **Data Retention and Reuse Policies** | Safety & reliability | — | Both | Both | — |
| **Minimum Data Access** | Safety & reliability | — | Both | Both | — |

## Prior authorization

12 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Prior authorization T&E framework](https://rai-content.chai.org/en/latest/prior-authorization-ai-supported-criteria-matching/t%26e-framework.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Reduce Turnaround Time (TAT)** | Usefulness, usability & efficacy | Usefulness | Both | Implementer | National average TAT for PA decisions is approximately 3-5 business days; Organizations should track % difference in improvement for TAT between non-AI v. AI PA solutions; Align to CMS Final Rule CMS-0057-F ("decisions within 72 hours for expedited requests and seven calendar days for standard… |
| **Policy Coverage Completeness** | Usefulness, usability & efficacy | Usefulness | Pre-Implementation | Developer | ≥ 90% of required, non-judgment policy coverage criteria accurately represented in benchmark datasets; ≤ 10% of objective policy coverage criteria (e.g., contraindications, lab thresholds) missing or mis-mapped. |
| **Time-on-Task** | Usefulness, usability & efficacy | Usability | Pre-Implementation | Implementer | ≥ ~15-30% reduction in time compared to baseline manual process is considered meaningful in utilization management operations |
| **Out-of-Task Question Handling** | Usefulness, usability & efficacy | Efficacy | Both | Developer | ≥ 95% correct rejection or redirection of out-of-scope queries in controlled testing scenarios |
| **Change in Performance due to Policy Updates** | Usefulness, usability & efficacy | Efficacy | Post-Implementation | Developer | No single benchmark; Developers should track any decline in key performance metrics post-policy update |
| **Appeal Overturn Rate** | Usefulness, usability & efficacy | Efficacy | Pre- and Post-Implementation | Implementer | The goal is to keep the Appeal Overturn Rate from rising above historical baselines during early adoption and to reduce it below pre-AI levels over time, showing that the AI solution decreases inappropriate denials and appeals. |
| **Predictive Parity (Positive Predictive Value Parity)** | Fairness & equity | Fairness | Both | Both | If subgroup PPV difference > 0.05, trigger review of training data composition, criteria mapping, or thresholding. |
| **Toxicity Language Score** | Fairness & equity | Bias Management | Both | Developer | Suggest a toxicity score < 0.1 (or 10%) generally indicates a low likelihood of the output being perceived as toxic, offensive, or biased by the average user; the goal is to have 0 toxic language. |
| **Auto-Approval vs. Manual Review Outcome Disparity** | Fairness & equity | Bias Management | Both | Both | — |
| **Demographic Appeal Delay Difference** | Fairness & equity | Bias Management | Pre-Implementation for… | Both | No recommended benchmark |
| **Failure Analysis** | Safety & reliability | Safety | Pre-Implementation | Both | Example benchmark includes: Risk Priority Number (RPN) < 100; the RPN scale typically ranges from 1 to 1000 (S, O, D each rated 1--10). A value of 100 (e.g., 5×5×4) indicates a moderate level of risk. Keeping all critical failure modes below 100 ensures that the AI solution does not go live with… |
| **Uptime Ratio / System Reliability** | Safety & reliability | Reliability | Both | Both | Vendor organizations should strive for system uptime ≥ 99.9% |

## Sepsis risk prediction

60 methods and metrics, with supporting literature and the full text of each
entry in
[CHAI's Sepsis risk prediction T&E framework](https://rai-content.chai.org/en/latest/sepsis-risk-prediction/te.html).

| Metric | Category | CHAI principle | When | Who | Benchmark |
|---|---|---|---|---|---|
| **Sequential Organ Failure Assessment (SOFA) score** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Risk Ratio** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Area under the curve (AUC)—precision recall curve (PRC) (AUC-PRC)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Precision (or Positive Predictive Value, PPV)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Recall (or Sensitivity)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Specificity** | Usefulness, usability & efficacy | — | Both | Both | — |
| **F1 score** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Root Mean Squared Error (RMSE)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Coefficient of Determination (R-squared)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Time-to-Event** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Inclusion / Exclusion Analysis** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Ground Theory Analysis** | Usefulness, usability & efficacy | — | Both | Both | — |
| **HOUsing-based SocioEconomic Status measure (HOUSES) Index** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Differential Missingness** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Equality of Opportunity Difference (EOD)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Confusion Matrix** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Equalized Odds** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Slice Finding** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Accuracy** | Safety & reliability | — | Both | Both | — |
| **Risk Framework** | Safety & reliability | — | Both | Both | — |
| **Task Analysis** | Safety & reliability | — | Both | Both | — |
| **Non-Inferiority Assessment** | Safety & reliability | — | Both | Both | — |
| **Likelihood of Failure at Identified Failure Points** | Safety & reliability | — | Both | Both | — |
| **Number of Successful Predictions** | Safety & reliability | — | Both | Both | — |
| **Percentage of Errors** | Safety & reliability | — | Both | Both | — |
| **Predetermined Change Control Plan** | Safety & reliability | — | Both | Both | — |
| **Saliency Maps** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Locally Interpretable Model-Agnostic Explanations (LIME)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Shapley Additive Explanation (SHAP)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Prototypical Explanations** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Availability of AI System Facts** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Locality of the assessment** | Safety & reliability | — | Both | Both | — |
| **Consult security experts** | Safety & reliability | — | Both | Both | — |
| **Leverage industry security guidelines** | Safety & reliability | — | Both | Both | — |
| **Data Protection Impact Assessments (DPIA)** | Safety & reliability | — | Both | Both | — |
| **Threat Modeling** | Safety & reliability | — | Both | Both | — |
| **Evaluation of the likelihood and impact of various attack vectors** | Safety & reliability | — | Both | Both | — |
| **Data Provenance Tracking** | Safety & reliability | — | Both | Both | — |
| **Numeric results from risk assessments** | Safety & reliability | — | Both | Both | — |
| **Outcomes of privacy preservation evaluations** | Safety & reliability | — | Both | Both | — |
| **System Usability Scale (SUS)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Usability Testing and Heuristic Evaluation** | Usefulness, usability & efficacy | — | Both | Both | — |
| **User Satisfaction Survey** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Sensitivity, Specificity, PPV** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Pre-post implementation differences in usefulness metrics** | Usefulness, usability & efficacy | — | Both | Both | — |
| **balanced error rate (BER)** | Fairness & equity | — | Both | Both | — |
| **Comparative Biases** | Fairness & equity | — | Both | Both | — |
| **Implement a process for identifying and recognizing model drift** | Fairness & equity | — | Both | Both | — |
| **False alarm rate** | Safety & reliability | — | Both | Both | — |
| **False negative rate** | Safety & reliability | — | Both | Both | — |
| **Proportion of patients who received IV antibiotics** | Safety & reliability | — | Both | Both | — |
| **Admissions and LOS differences** | Safety & reliability | — | Both | Both | — |
| **Technical Support** | Safety & reliability | — | Both | Both | — |
| **Random Forest** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Determine who on the care team is receiving alerts (components of screening)** | Usefulness, usability & efficacy | — | Both | Both | — |
| **Dynamic Post-implementation Audits** | Safety & reliability | — | Both | Both | — |
| **Limiting Access to AI Models** | Safety & reliability | — | Both | Both | — |
| **Intercepting AI Model Outputs** | Safety & reliability | — | Both | Both | — |
| **Input Filtering** | Safety & reliability | — | Both | Both | — |
| **Authenticated Inputs or Inputs with Provenance** | Safety & reliability | — | Both | Both | — |

---

**279 metrics across 10 use cases.**
