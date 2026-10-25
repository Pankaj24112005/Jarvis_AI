# Experimental Research Plan: Evaluating Deterministic Invariant Verification and Bounded Recovery in Desktop AI Agents

**Project:** JARVIS Research Feasibility Evaluation  
**Workspace:** `d:/my work/Jarves gemini/research_publication_assessment/`  
**Assessment Date:** October 9, 2026  
**Lead Investigator:** Senior AI Systems & Empirical Research Scientist  

---

## 1. Research Problem & Core Hypotheses

### 1.1 The Research Problem
Multimodal Large Language Model (MLLM) agents operating on graphical desktop environments suffer from two prevalent failure modes during complex task execution:
1. **Silent Outcome Misalignment (Hallucinated Success)**: The agent executes an OS action (e.g., launching an application or clicking a button), assumes immediate success from tool invocation alone, and proceeds with downstream steps even when the target window lagged, failed to focus, or the click missed.
2. **Cascading Side-Effect Loops**: When encountering task friction or errors, unconstrained LLM agents (e.g., standard ReAct or Reflexion) frequently generate repetitive retries of mutating actions (e.g., submitting forms multiple times, duplicate application launches, or overwriting files), causing cascading state corruption and infinite action cycling ($A-B-A-B$).

### 1.2 Formal Research Hypotheses
* **Hypothesis 1 ($H_1$) — Execution Integrity**: Gating desktop agent execution with a multi-tier deterministic outcome verifier (`StepVerifier`) will significantly increase end-to-end Task Completion Rate (TSR) by intercepting silent GUI race conditions before error propagation occurs.
* **Hypothesis 2 ($H_2$) — Side-Effect Mitigation**: Restricting agent retry logic through a canonical tri-state idempotency table and deterministic cycle detection (`RecoveryPolicy` + `AntiLoopGuard`) will reduce unintended duplicate system mutations to **0%**, whereas unconstrained LLM self-reflection baselines will exhibit non-zero mutation rates.
* **Hypothesis 3 ($H_3$) — Computational & Token Efficiency**: Deterministic, non-LLM recovery evaluation will reduce mean recovery decision latency by over **90%** and reduce total API token consumption per task by over **25%** compared to verbal reflection methods (Reflexion).

---

## 2. Research Questions (RQs)

* **RQ1 (Task Effectiveness)**: To what extent does multi-tier sensory verification improve task success across diverse desktop workflows compared to unverified execution?
* **RQ2 (Safety & Idempotency)**: How effectively does canonical idempotency filtering prevent destructive side-effect cascades under controlled GUI failure injections?
* **RQ3 (Loop Prevention)**: How frequently do baseline agents fall into alternating action loops ($A-B-A-B$) in desktop automation, and does deterministic history fingerprinting completely eliminate them?
* **RQ4 (System Overhead)**: What is the computational, latency, and token overhead of deterministic outcome verification versus LLM-based verbal self-reflection?

---

## 3. Experimental Baselines

To rigorously evaluate the mechanism implemented in JARVIS, we define three explicit comparative baselines:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Baseline 1: Naive Execution (Standard ReAct)                           │
│ - Uses Gemini tool-calling loop (thought -> action -> observation).   │
│ - Tool execution return code is treated as ground-truth success.       │
│ - If tool returns error, the LLM is prompted blindly to try again.    │
├────────────────────────────────────────────────────────────────────────┤
│ Baseline 2: Verbal Self-Reflection (Reflexion-style)                   │
│ - Post-action screen screenshot is fed back to Gemini Vision.          │
│ - Gemini Vision verbally analyzes whether the action succeeded.        │
│ - If evaluated as failure, Gemini generates verbal reflection and      │
│   prompts a new recovery action without idempotency restrictions.      │
├────────────────────────────────────────────────────────────────────────┤
│ Baseline 3: JARVIS Framework (Proposed Deterministic System)           │
│ - Post-action evaluated via deterministic hierarchy in StepVerifier.   │
│ - Recovery evaluated via deterministic RecoveryPolicy (idempotency,   │
│   cycle detection, anti-loop guards, settling delays). Zero LLM in    │
│   recovery path.                                                       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Benchmark Dataset & Desktop Task Suite

We construct a standardized, reproducible benchmark suite comprising **60 diverse desktop tasks** across four core operational categories, adapted from OSWorld and real-world executive assistant workflows:

| Category | Number of Tasks | Representative Task Scenarios | Required Tools | Success Verification Criteria |
| :--- | :---: | :--- | :--- | :--- |
| **A. Filesystem & Terminal** | 15 | Create project scaffold, search logs for error keywords, archive output directory, update config files. | `filesystem_*`, `terminal_execute` | File existence, md5 hash check, exit code == 0, content verification. |
| **B. Desktop App Lifecycle** | 15 | Launch Calculator, perform arithmetic, focus window, close gracefully; launch Paint, save canvas. | `launch_application`, `focus_application`, `close_application` | Target HWND presence, window title match, process tree inspection. |
| **C. Web & Browser Research**| 15 | Navigate to Python docs, find specific PEP summary, copy code snippet to local file, close active tab. | `browser_open`, `browser_read_page`, `browser_control` | Active tab URL inspection, target text extracted, browser process preserved. |
| **D. Multimodal UI Grounding**| 15 | Locate and click "Save As" dialog button, select radio button in settings window, click submit icon. | `visual_grounding_click`, `capture_screen` | UI state change detected via image delta and active focus shift. |

---

## 5. Controlled Failure Injection Protocols

To evaluate resilience under real-world operating system instability, we inject controlled faults into 50% of test trials:

1. **Fault Type 1 — Foreground Focus Lag (GUI Race Condition)**: Introduce a synthetic 1.5-second delay before window foreground promotion during application launches.
2. **Fault Type 2 — Transient Target Occlusion**: Programmatically render a temporary overlay window for 500ms covering the visual grounding target.
3. **Fault Type 3 — Non-Idempotent Tool Failure**: Simulate an ambiguous outcome during file write or process termination to test whether the agent attempts an unauthorized secondary modification.
4. **Fault Type 4 — Web Driver Latency**: Introduce a 3-second artificial network throttle during web page DOM rendering.

---

## 6. Variables & Quantitative Metrics

### 6.1 Independent Variables
- **System Architecture**: Baseline 1 (ReAct), Baseline 2 (Reflexion), Baseline 3 (JARVIS Full).
- **Environment Condition**: Clean Execution vs. Controlled Fault Injection.

### 6.2 Dependent Variables & Formal Metrics

| Metric | Code / Formulation | Unit | Scientific Significance |
| :--- | :---: | :---: | :--- |
| **Task Success Rate (TSR)** | $\frac{N_{\text{success}}}{N_{\text{total}}} \times 100\%$ | % | Measures overall problem-solving efficacy. |
| **Unsafe Side-Effect Rate (USER)** | $\frac{N_{\text{illegal mutations}}}{N_{\text{total tasks}}} \times 100\%$ | % | Measures safety: duplicate writes, extra process launches, form resubmissions. |
| **Action Loop Rate (ALR)** | $\frac{N_{\text{cyclic loops}}}{N_{\text{total tasks}}} \times 100\%$ | % | Frequency of entering repetitive $A-B-A-B$ cycles. |
| **Recovery Latency Overhead** | $T_{\text{recovery decision}}$ | Milliseconds | Time taken to decide whether and how to recover from a failure. |
| **Token Consumption** | Total Tokens per Task | Tokens | Cumulative input/output token cost paid to foundation model API. |
| **Verification Accuracy** | $\frac{TP + TN}{TP + TN + FP + FN}$ | % | Precision and recall of the verifier against ground truth physical state. |

---

## 7. Experimental Procedure & Statistical Rigor

### 7.1 Trial Execution Protocol
* **Sample Size**: 60 benchmark tasks $\times$ 3 system configurations $\times$ 3 repetitions = **540 experimental runs**.
* **Clean State Reset**: Before each trial, the OS environment is reset using automated PowerShell cleanup scripts:
  - Kill non-essential background child processes.
  - Reset test workspace folders to a clean Git commit.
  - Clear browser session storage and temporary cache files.
* **Isolation**: All tests run in an isolated test fixture environment; secrets are mocked, and OS actions operate within dedicated sandbox directories.

### 7.2 Statistical Hypothesis Testing
* For continuous metrics (Latency, Token Consumption): Perform **Two-Sample Student's $t$-Test** (or non-parametric **Wilcoxon Signed-Rank Test** if normality is rejected by Shapiro-Wilk test). Significance threshold: $\alpha = 0.01$.
* For categorical rates (TSR, USER, ALR): Perform **McNemar's Test** for paired binary outcomes.
* **Effect Size**: Calculate **Cohen's $d$** to quantify practical significance.

---

## 8. Ablation Study Matrix

To isolate the individual contribution of each engineering component, we specify a 4-tier ablation matrix:

| Configuration | Outcome Verifier | Canonical Idempotency | Anti-Loop Guard | Launch Settling Delay |
| :--- | :---: | :---: | :---: | :---: |
| **Full JARVIS System** | **Active** | **Active** | **Active** | **Active** |
| *Ablation 1: No Verifier* | Disabled (Blind) | Active | Active | Active |
| *Ablation 2: No Idempotency* | Active | Disabled (Unrestricted) | Active | Active |
| *Ablation 3: No Anti-Loop* | Active | Active | Disabled (No cycle check) | Active |
| *Ablation 4: No Launch Guard* | Active | Active | Active | Disabled (Blind relaunch) |

### Expected Insights from Ablations:
- *Ablation 1* isolates the exact performance boost provided by physical state inspection.
- *Ablation 2* reveals the precise rate of duplicate side-effects prevented by canonical classification.
- *Ablation 3* quantifies the necessity of $A-B-A-B$ cycle detection.
- *Ablation 4* measures how many duplicate application processes spawn during GUI race conditions without settling delays.

---

## 9. Threats to Validity

### 9.1 Internal Validity
- **Foundation Model Drift**: Gemini API updates on Google's cloud servers could alter reasoning baseline performance over time.  
  *Mitigation*: Pin model version strings (`gemini-2.5-flash-001` or specific snapshot tags) and record exact request/response JSON payloads.
- **System Load Variations**: OS background tasks could affect active-window lookup latencies.  
  *Mitigation*: Execute all benchmarks on a dedicated workstation with static process priorities and record multiple trials.

### 9.2 External Validity
- **Operating System Generalizability**: The current implementation utilizes Windows-specific window handles (`HWND`) and UWP URI schemes.  
  *Mitigation*: Explicitly document Windows as the target evaluation environment and specify Linux/macOS abstraction requirements in the discussion.

### 9.3 Construct Validity
- **Task Representativeness**: 60 synthetic tasks may not capture the full entropy of real-world human computer use.  
  *Mitigation*: Adopt established task templates from OSWorld and include noisy, ambiguous user prompts.
