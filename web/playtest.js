"use strict";
(() => {
  const byId = id => document.getElementById(id);
  const setText = (id, text) => { const node = byId(id); if (node.textContent !== text) node.textContent = text; };
  let current = null;
  let csrf = "";
  let authenticated = false;
  let busy = false;
  let online = false;
  let confirmedAt = null;
  let generation = 0;
  let feedbackBusy = false;
  let evidenceFingerprint = "";
  let correctionFingerprint = "";
  let sdkFingerprint = "";
  let cardFingerprint = "";
  let publicationIdentity = "";
  let publicationDeadline = 0;
  let inspected = false;
  let publicIssue = "";
  let matchesUsed = null;
  let maxMatches = 3;
  let nextAction = "pattern";
  let copyCasesFingerprint = "";
  let copyAdviceFingerprint = "";
  let copyAwaitingState = false;
  let copyInUse = false;
  let guidedStream = null;
  let inspectedContext = "";
  let nextUnavailable = true;
  let feedbackAttempt = null;
  let primaryCooling = false;
  const retiredStreams = new Set();

  function idempotencyId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return Array.from(crypto.getRandomValues(new Uint8Array(24)), value => value.toString(16).padStart(2, "0")).join("");
  }
  function say(text, error = false) {
    const notice = byId("global-notice");
    notice.hidden = !text;
    if (notice.textContent !== text) notice.textContent = text;
    notice.classList.toggle("error", error);
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, signal: controller.signal });
      let data = null;
      try { data = await response.json(); } catch (_) { /* Never surface raw HTML or stack traces. */ }
      if (!response.ok) {
        const error = new Error(response.status === 429
          ? "This session reached a usage limit. Wait before trying again, or ask the playtest owner about access."
          : [401, 403].includes(response.status)
            ? "Your playtest session has expired or could not be verified. Sign in again from the home page."
            : response.status === 409
              ? "The replay changed before this action completed. Check the refreshed facts before repeating it."
              : response.status >= 500
                ? "The replay service is temporarily unavailable. Your last confirmed facts are shown below."
                : "That action could not be completed. Check the current replay before trying again.");
        error.status = response.status;
        throw error;
      }
      if (!data || typeof data !== "object") throw new Error("The service returned an unreadable response. Please try again shortly.");
      return data;
    } finally { clearTimeout(timer); }
  }
  function expireSession() {
    authenticated = false; csrf = ""; online = false;
    say("Your playtest session has expired. Use Sign out to return home and enter your access code again. Your feedback draft has not been sent.", true);
    updateControls(); updateFreshness();
  }
  function updateFreshness() {
    const freshness = byId("freshness");
    freshness.classList.toggle("offline", !online);
    setText("freshness", online ? "Connected · confirmed replay facts" : confirmedAt ? "Offline · showing last confirmed facts" : "Connecting · facts not yet confirmed");
    if (confirmedAt) {
      setText("last-confirmed", "Last confirmed at " + new Date(confirmedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " on this device.");
    }
  }
  function updateControls() {
    const unavailable = busy || copyAwaitingState || !authenticated || !online || !current;
    document.querySelectorAll("[data-action],#audience,#language,#new-match,#new-match-confirm").forEach(node => { node.disabled = unavailable; });
    byId("replay").disabled = unavailable || !current?.recorded_replay?.available;
    if (Number.isInteger(matchesUsed) && matchesUsed >= maxMatches) byId("new-match").disabled = true;
    byId("inspect-evidence").disabled = !current;
    byId("feedback-submit").disabled = feedbackBusy || !authenticated;
    byId("feedback-delete").disabled = feedbackBusy || !authenticated;
    byId("feedback-delete-confirm").disabled = feedbackBusy || !authenticated;
    const replay = current?.recorded_replay;
    setText("replay-help", replay?.available
      ? "Replays an accepted historical selection against its original facts. No model request is made."
      : current?.envelope?.provenance?.corrections?.length
        ? "The approved correction changed the original state. Its old recorded replay stays blocked. Rewind keeps the correction; a new match creates a separate fixture."
        : "Show the original 50-second moment first to make its recorded selection available.");
    const hasCorrection = current ? correctionRows(current).some(row => row.before.goal === true && row.after.goal === false) : false;
    document.querySelectorAll("[data-action='correct']").forEach(node => { node.disabled = unavailable || current.publication.event_time.through_ms < 50000 || hasCorrection; });
    let next = "pattern";
    // A displayed final recap remains complete after reopen/reload, even
    // though recovery correctly discards transient copy advice and drafts.
    if (current && current.position === current.positions - 1) next = "complete";
    else if (current && current.publication.event_time.through_ms >= 50000) {
      if (!current.copy_review) next = hasCorrection ? inspected ? "finish" : "evidence" : "correct";
      else {
        const review = current.copy_review;
        const matchingAdvice = caseId => !review.evidence_error && copyPresentationMatches()
          && ["reviewed", "approved_copy_draft"].includes(review.status)
          && review.advice?.case_id === caseId
          && review.cases?.some(row => row.case_id === caseId && row.available === true);
        const pendingApproval = !review.evidence_error && review.status === "reviewed" && review.advice?.case_id === "P03"
          && review.advice?.can_approve === true && ["allow", "revise"].includes(review.advice?.decision)
          && review.cases?.some(row => row.case_id === "P03" && row.available === true);
        const approved = matchingAdvice("P03") && review.status === "approved_copy_draft"
          && typeof review.advice?.advice_id === "string" && review.advice.advice_id.length > 0
          && review.producer_copy_draft
          && review.producer_copy_draft?.advice_id === review.advice?.advice_id;
        next = hasCorrection ? !matchingAdvice("P04") ? "review_after" : !inspected ? "evidence" : "finish"
          : approved ? "correct" : pendingApproval ? "approve_before" : "review_before";
        // Recorded fixtures exist only at their exact 50s fact snapshots.
        // Offer a real route back instead of a permanently disabled step.
        if (["review_before", "review_after"].includes(next) && copyPresentationMatches()
            && !review.evidence_error && current.publication.event_time.through_ms !== 50000) next = "review_moment";
      }
    }
    nextAction = next;
    const nextCopy = {
      pattern: ["1. Show the 50s moment", "Start with the fictional match facts. No live model calls."],
      review_before: ["2. Review the mixed draft", "Replay the recorded advice: retain the shot count and drop the false passing clause."],
      approve_before: ["3. Approve the retained wording", "Save only the supported original clause as a producer draft. Nothing is transmitted."],
      correct: ["4. Correct the goal", "The goal leaves the score while the on-target shot stays in the record."],
      review_after: ["5. Review copy after the correction", "See the recorded advice and its wrong reason, beside the actual goal-withdrawal evidence."],
      evidence: ["6. Inspect the changed evidence", "Read the changed goal event first, then the remaining events in time order."],
      finish: ["7. Show the final recap", "Review the corrected final score and what still counts."],
      complete: ["Recap ready", "The final recap is ready below. Rewind keeps approved corrections so you can review the 50-second moment again."],
      review_moment: ["Return to the 50s review", "Show the matching moment again. Approved corrections remain in the event record."],
      presentation: ["Use English Fan summary for review", "Choose Fan summary and English below; the app will not change your presentation automatically."]
    };
    let permitted = true;
    if (["review_before", "review_after"].includes(next)) {
      const caseId = next === "review_before" ? "P03" : "P04";
      permitted = copyPresentationMatches() && !copyAwaitingState && !current.copy_review.evidence_error
        && current.copy_review.cases?.some(row => row.case_id === caseId && row.available === true);
    } else if (next === "approve_before") {
      permitted = copyPresentationMatches() && !copyAwaitingState && current.copy_review?.status === "reviewed"
        && current.copy_review.advice?.case_id === "P03" && current.copy_review.advice?.can_approve === true
        && ["allow", "revise"].includes(current.copy_review.advice?.decision);
    }
    const presentationBlocked = ["review_before", "review_after", "approve_before"].includes(next) && !copyPresentationMatches();
    const copy = nextCopy[presentationBlocked ? "presentation" : next];
    setText("next-action", copy[0]);
    setText("next-action-help", copyAwaitingState ? "Waiting for a fresh replay response before continuing. Last confirmed facts remain visible."
      : permitted || presentationBlocked ? copy[1] : "This step is unavailable for the current facts or pending response. Check the copy-review status below.");
    nextUnavailable = unavailable || !permitted || primaryCooling || next === "complete";
    // Keep the focused primary button in the tab order during a request.
    byId("next-action").disabled = !authenticated || !online || !current;
    byId("next-action").setAttribute("aria-disabled", String(nextUnavailable));
    byId("next-action").setAttribute("aria-busy", String(busy));
    document.querySelectorAll(".journey-button,[data-action='finish']").forEach(node => {
      const matches = (node.dataset.action || "evidence") === nextAction;
      node.classList.toggle("next-step", matches);
      if (matches) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current");
    });
    updateCopyControls();
  }
  function syncGuidedProgress(s) {
    if (guidedStream !== s.publication.stream_id) {
      guidedStream = s.publication.stream_id;
      inspected = false;
    }
    const context = JSON.stringify({ through: s.publication.event_time.through_ms,
      revisions: s.envelope.provenance.event_revisions, records: s.envelope.provenance.evidence_records });
    if (context !== inspectedContext) inspected = false;
    inspectedContext = context;
  }
  function revealResult(id, primary = false) {
    const target = byId(id);
    const guideHeight = byId("primary-guide")?.getBoundingClientRect?.().height;
    if (target?.style) target.style.scrollMarginTop = `${Number.isFinite(guideHeight) ? guideHeight + 20 : 160}px`;
    target?.scrollIntoView?.({ block: "start", behavior: "instant" });
    if (primary) byId("next-action").focus?.({ preventScroll: true });
    else { target?.setAttribute("tabindex", "-1"); target?.focus?.({ preventScroll: true }); }
  }
  async function runNextAction() {
    if (nextUnavailable || busy || primaryCooling) return;
    // Cover every primary action, including very fast local responses, so a
    // double Enter/tap cannot skip the newly displayed result at any step.
    primaryCooling = true;
    setTimeout(() => { primaryCooling = false; updateControls(); }, 500);
    if (nextAction === "evidence") {
      byId("evidence-panel").hidden = false; byId("inspect-evidence").setAttribute("aria-expanded", "true");
      inspected = true; updateControls(); setText("action-status", "Changed evidence opened. The next step is the final recap.");
      revealResult("evidence-title", true); return;
    }
    if (["review_before", "review_after"].includes(nextAction)) {
      const caseId = nextAction === "review_before" ? "P03" : "P04";
      copyInUse = true; byId("copy-case").value = caseId;
      return control({ action: "review_copy", case_id: caseId }, { primary: true });
    }
    if (nextAction === "approve_before") {
      copyInUse = true; return control({ action: "approve_copy", advice_id: current.copy_review.advice.advice_id }, { primary: true });
    }
    return control({ action: nextAction === "review_moment" ? "pattern" : nextAction }, { primary: true });
  }
  function selectedCopyCase() { return current?.copy_review?.cases?.find(row => row.case_id === byId("copy-case")?.value); }
  function copyPresentationMatches() { return current?.audience === "casual" && current?.language === "en"; }
  function canReviewCopy() {
    return authenticated && online && !busy && !copyAwaitingState && !current?.copy_review?.evidence_error && current?.copy_review?.mode === "recorded"
      && copyPresentationMatches() && selectedCopyCase()?.available === true;
  }
  function canApproveCopy() {
    const review = current?.copy_review, advice = review?.advice;
    return canReviewCopy() && review.status === "reviewed" && advice?.case_id === selectedCopyCase()?.case_id
      && advice?.can_approve === true && ["allow", "revise"].includes(advice.decision)
      && typeof advice.advice_id === "string" && advice.advice_id.length > 0;
  }
  function updateCopyControls() {
    if (!byId("copy-review")) return;
    const review = current?.copy_review, enabled = review?.mode === "recorded";
    byId("copy-review").hidden = !enabled;
    byId("copy-case").disabled = !enabled || !authenticated || !online || busy || copyAwaitingState || Boolean(review?.evidence_error)
      || !copyPresentationMatches() || !(review?.cases || []).some(row => row.available === true);
    byId("copy-review-button").disabled = !canReviewCopy();
    byId("copy-approve").disabled = !canApproveCopy();
    setText("copy-approve", nextAction === "approve_before" ? "Save retained wording" : "Optional: save retained wording");
    byId("copy-clear").disabled = !enabled || !authenticated || !online || busy || copyAwaitingState
      || !["reviewed", "approved_copy_draft"].includes(review?.status);
    if (!enabled) return;
    const selected = selectedCopyCase();
    setText("copy-availability", review.evidence_error
      ? "Recorded review evidence is unavailable. No wording can be reviewed or approved."
      : !copyPresentationMatches()
      ? "These recordings support Fan summary in English only. Choose that presentation to review a matching 50-second sample. The broadcast presentation is not changed automatically."
      : selected?.available === true
        ? "This recorded sample matches the current facts. Reviewing it makes no model request."
        : "Samples become available at their matching 50-second facts. Show the moment first. The corrected facts have a separate recorded sample.");
    byId("copy-status").setAttribute("aria-live", copyInUse ? "polite" : "off");
    setText("copy-status", !copyInUse ? "" : copyAwaitingState
      ? "Action not confirmed. Approval is paused until a fresh replay response confirms the current facts."
      : !authenticated ? "Your session is unavailable. Sign in again before reviewing or approving wording."
      : !online ? "Cached review. Replay service unavailable; wording cannot be approved."
      : busy ? "Waiting for the replay response. No new model call."
      : !copyPresentationMatches() ? "Copy review is unavailable for this presentation."
      : review.status === "stale" ? "Facts changed. Previous advice and any producer draft are no longer current. Review a matching sample again."
      : review.status === "approved_copy_draft" ? "Producer draft saved in your session. The broadcast preview is unchanged."
      : review.status === "reviewed" && review.advice?.case_id !== selected?.case_id ? "A different sample is selected. Review it before approving wording."
      : review.status === "reviewed" && review.advice?.decision === "withhold" ? "Withhold this draft. No wording can be approved from this review."
      : review.status === "reviewed" ? "Check the original clauses and supporting facts. Approve only the retained wording."
      : review.status === "cleared" ? "Copy review cleared. The broadcast preview is unchanged."
      : "Choose an available sample to review its wording before saving a producer draft.");
  }
  function renderCopyReview(s) {
    if (!byId("copy-review")) return;
    const review = s.copy_review;
    const clearedTimeout = s.recorded_replay?.status === "injected_timeout" && review?.status === "cleared"
      && !review.advice && !review.producer_copy_draft;
    byId("copy-recovery-result").hidden = !clearedTimeout;
    setText("copy-recovery-facts", clearedTimeout
      ? "Checked score retained: " + Object.entries(s.publication.facts.score).map(([name, goals]) => `${name} ${goals}`).join(" · ") + "."
      : "");
    if (review?.mode !== "recorded") {
      byId("copy-review").hidden = true; byId("copy-advice").hidden = true; byId("copy-approved").hidden = true;
      byId("copy-clauses").replaceChildren(); byId("copy-facts").replaceChildren(); setText("copy-raw", ""); setText("copy-approved-text", "");
      copyCasesFingerprint = ""; copyAdviceFingerprint = ""; return;
    }
    const evaluation = review.evaluation || {};
    setText("copy-evaluation", `Recorded pilot: ${evaluation.strict_passes ?? "?"}/${evaluation.total ?? "?"} strict passes. ${evaluation.status || "UNQUALIFIED"}: one recorded reason mismatch remains; not qualified for production.`);
    const cases = Array.isArray(review.cases) ? review.cases : [];
    const caseFingerprint = JSON.stringify(cases);
    if (caseFingerprint !== copyCasesFingerprint) {
      copyCasesFingerprint = caseFingerprint;
      const previous = byId("copy-case").value;
      const names = { P01: "Supported shot summary", P02: "Unsupported pressing explanation", P03: "Mixed shot and passing claim", P04: "Copy after the goal correction" };
      byId("copy-case").replaceChildren();
      for (const row of cases) {
        const option = document.createElement("option"); option.value = row.case_id; option.disabled = row.available !== true;
        option.textContent = `${names[row.case_id] || "Recorded sample"}${row.available === true ? "" : " (unavailable)"}`;
        byId("copy-case").append(option);
      }
      byId("copy-case").value = cases.find(row => row.case_id === previous && row.available === true)?.case_id
        || cases.find(row => row.case_id === review.advice?.case_id && row.available === true)?.case_id
        || cases.find(row => row.case_id === "P03" && row.available === true)?.case_id
        || cases.find(row => row.available === true)?.case_id || "";
    }
    const visible = !review.evidence_error && copyPresentationMatches() && ["reviewed", "approved_copy_draft"].includes(review.status);
    const advice = visible && cases.some(row => row.case_id === review.advice?.case_id && row.available === true) ? review.advice : null;
    const draft = review.status === "approved_copy_draft" && advice && review.producer_copy_draft?.advice_id === advice.advice_id ? review.producer_copy_draft : null;
    const fingerprint = JSON.stringify({ advice, draft });
    if (fingerprint === copyAdviceFingerprint) return;
    copyAdviceFingerprint = fingerprint;
    byId("copy-advice").hidden = !advice; byId("copy-approved").hidden = !draft;
    byId("copy-clauses").replaceChildren(); byId("copy-facts").replaceChildren(); setText("copy-raw", ""); setText("copy-approved-text", "");
    byId("copy-raw-details").open = false; byId("copy-pilot-warning").hidden = true;
    if (advice) {
      const labels = { allow: "Keep this wording", revise: "Keep only the supported clauses", withhold: "Withhold this draft" };
      setText("copy-decision", labels[advice.decision] || "Review unavailable");
      setText("copy-recorded-reason", "Recorded reviewer reason: " + String(advice.raw_reason || "Not supplied").replace(/_/g, " ") + ".");
      const checked = advice.deterministic_classification || {};
      setText("copy-checked-reason", `Fact check: ${checked.explanation || String(checked.reason || "Not supplied").replace(/_/g, " ")}${checked.evidence_ids?.length ? ` Evidence: ${checked.evidence_ids.join(", ")}.` : ""}`);
      const correction = correctionRows(s).find(row => row.target_event_id === "e010" && row.before.goal === true && row.after.goal === false && row.to_revision === 2);
      const currentShot = s.envelope.provenance.evidence_records?.find(row => row.id === "e010");
      const reasonMismatch = advice.case_id === "P04" && correction && currentShot?.goal === false
        && s.envelope.provenance.event_revisions?.e010 === 2 && checked.reason === "stale_revision"
        && typeof advice.raw_reason === "string" && advice.raw_reason !== checked.reason;
      byId("copy-pilot-warning").hidden = !reasonMismatch;
      setText("copy-pilot-warning", reasonMismatch ? "Suggested right words, but the recorded reviewer gave the wrong reason. The event record shows the goal was withdrawn at e010 revision 2. Its approved correction explains why the old wording is stale. The original strict pilot result remains 3/4 NO_GO." : "");
      for (const clause of advice.clauses || []) {
        const row = document.createElement("li"), tag = document.createElement("strong"), original = document.createElement("p"), proof = document.createElement("small");
        row.className = clause.disposition === "keep" ? "copy-keep" : "copy-drop";
        tag.textContent = `${clause.disposition === "keep" ? "Keep" : clause.disposition === "drop" ? "Drop" : "Unqualified"} ${clause.id}`;
        original.textContent = clause.text; proof.textContent = clause.evidence_ids?.length ? "Evidence: " + clause.evidence_ids.join(", ") : "No supporting evidence linked for this clause.";
        row.append(tag, original, proof); byId("copy-clauses").append(row);
      }
      for (const fact of advice.facts || []) {
        const row = document.createElement("li"), text = document.createElement("p"), proof = document.createElement("small");
        text.textContent = fact.text;
        proof.textContent = `${fact.fact_id}: ${(fact.evidence_ids || []).map(id => `${id}${fact.event_revisions?.[id] !== undefined ? ` revision ${fact.event_revisions[id]}` : ""}`).join(", ")}`;
        row.append(text, proof); byId("copy-facts").append(row);
      }
      setText("copy-raw", JSON.stringify({ mode: "recorded", new_model_calls: 0, case_id: advice.case_id, advice_id: advice.advice_id, binding: advice.binding, raw_reason: advice.raw_reason, deterministic_classification: checked, receipt_sha256: advice.receipt_sha256, recorded_trace: advice.recorded_trace }, null, 2));
    }
    if (draft) setText("copy-approved-text", draft.text);
  }
  function showSessionLimits() {
    setText("session-limits", Number.isInteger(matchesUsed)
      ? `Controlled free playtest · ${matchesUsed} of ${maxMatches} personal match generations used.`
      : `Controlled free playtest · up to ${maxMatches} personal match generations per session.`);
    byId("new-match").disabled = busy || !authenticated || !online || !current || (Number.isInteger(matchesUsed) && matchesUsed >= maxMatches);
  }
  function correctionRows(s) {
    const through = s.publication.event_time.through_ms;
    return (s.envelope.provenance.corrections || []).filter(row => row.before && row.after && row.before.at_ms <= through && row.after.at_ms <= through);
  }
  function renderCorrections(s) {
    const rows = correctionRows(s);
    const fingerprint = JSON.stringify(rows);
    if (fingerprint === correctionFingerprint) return;
    correctionFingerprint = fingerprint;
    const container = byId("correction-summary");
    container.replaceChildren();
    if (!rows.length) {
      const p = document.createElement("p"); p.textContent = "No approved correction is visible at this replay time.";
      const hint = document.createElement("p"); hint.className = "small"; hint.textContent = "Show the 50-second moment, then try the goal correction.";
      container.append(p, hint); return;
    }
    for (const row of rows) {
      const heading = document.createElement("p");
      const title = document.createElement("strong");
      const withdrawn = row.before.goal === true && row.after.goal === false;
      title.textContent = withdrawn ? "Goal withdrawn. Shot retained." : "An approved event correction is visible.";
      heading.append(title);
      const list = document.createElement("ul"); list.className = "correction-diff";
      const lines = [
        `${row.target_event_id || row.after.id}: revision ${row.from_revision} → ${row.to_revision}`,
        ...(withdrawn ? ["Goal: yes → no", `Shot on target: ${row.after.on_target ? "yes, unchanged" : "no"}`] : [])
      ];
      for (const text of lines) { const item = document.createElement("li"); item.textContent = text; list.append(item); }
      const note = document.createElement("p"); note.className = "small";
      note.textContent = "Rewind keeps this correction. The original publication was replaced; the historical shot count can remain supported.";
      container.append(heading, list, note);
    }
  }
  function renderEvidence(s) {
    const provenance = s.envelope.provenance;
    const records = [...(provenance.evidence_records || [])].sort((a, b) => a.at_ms - b.at_ms || String(a.id).localeCompare(String(b.id)));
    const changedIds = new Set(correctionRows(s).map(row => row.target_event_id || row.after.id));
    const fingerprint = JSON.stringify({ records, revisions: provenance.event_revisions, changedIds: [...changedIds] });
    if (fingerprint === evidenceFingerprint) return;
    evidenceFingerprint = fingerprint;
    const list = byId("evidence-list"); list.replaceChildren();
    const visible = records.filter(event => event.type !== "metadata");
    function eventCard(event) {
      const article = document.createElement("article"); article.className = "evidence-event";
      const revision = provenance.event_revisions?.[event.id] || 1;
      if (revision > 1) article.classList.add("corrected");
      const title = document.createElement("h3"); title.textContent = `${event.id}: revision ${revision}`;
      const description = document.createElement("p");
      description.textContent = `${(event.at_ms / 1000).toFixed(0)}s: ${event.type === "shot" ? "Shot" : event.type.charAt(0).toUpperCase() + event.type.slice(1)}; ${event.team_id === "harbor" ? "Harbor Owls" : event.team_id === "meadow" ? "Meadow Foxes" : "Fictional event"}`;
      article.append(title, description);
      if (event.type === "shot") {
        const facts = document.createElement("div"); facts.className = "event-facts";
        for (const text of [`On target: ${event.on_target ? "yes" : "no"}`, `Goal: ${event.goal ? "yes" : "no"}`]) { const chip = document.createElement("span"); chip.textContent = text; facts.append(chip); }
        article.append(facts);
      }
      return article;
    }
    const groups = [
      { title: "Changed by the approved correction", changed: true, events: visible.filter(event => changedIds.has(event.id)) },
      { title: changedIds.size ? "Other visible events, in time order" : "Visible events, in time order", changed: false, events: visible.filter(event => !changedIds.has(event.id)) }
    ];
    for (const group of groups) {
      if (!group.events.length) continue;
      const section = document.createElement("section"), title = document.createElement("h3");
      section.className = group.changed ? "evidence-group changed-group" : "evidence-group";
      title.textContent = group.title; section.append(title);
      for (const event of group.events) section.append(eventCard(event));
      list.append(section);
    }
    if (!visible.length) { const p = document.createElement("p"); p.className = "small"; p.textContent = "No match events are visible yet. Show the 50-second moment."; list.append(p); }
    setText("evidence-raw", JSON.stringify(records, null, 2));
  }
  function renderFanCorrection(s) {
    const provenance = s.envelope.provenance;
    const correction = correctionRows(s).find(row => row.before.goal === true && row.after.goal === false
      && provenance.event_revisions?.[row.target_event_id] === row.to_revision);
    const shot = correction && provenance.evidence_records?.find(row => row.id === correction.target_event_id);
    const supported = s.audience === "casual" && ["en", "es"].includes(s.language) && shot?.type === "shot" && shot.goal === false;
    byId("fan-correction-summary").hidden = !supported;
    byId("fan-correction-summary").lang = s.language;
    setText("fan-correction-summary", supported
      ? s.language === "es"
        ? `El gol se anuló en el marcador. El intento sigue contando como ${shot.on_target === true ? "un tiro a puerta" : "un tiro"}.`
        : `The goal was removed from the score. The attempt still counts as ${shot.on_target === true ? "a shot on target" : "a shot"}.`
      : "");
  }
  function renderSdk(s) {
    const through = s.publication.event_time.through_ms;
    const records = (s.recorded_framework_trace?.receipts || []).filter(row => row.historical_only === true && row.through_ms <= through);
    const moments = (s.recap.recorded_selections || []).filter(row => row.historical_only === true && row.original_through_ms <= through);
    const fingerprint = JSON.stringify({ records, moments });
    if (fingerprint === sdkFingerprint) return;
    sdkFingerprint = fingerprint;
    const container = byId("sdk-summary"); container.replaceChildren();
    if (!records.length) { const p = document.createElement("p"); p.className = "small"; p.textContent = "Recorded selections appear once the replay reaches their original event time. Show the 50-second moment to inspect them."; container.append(p); return; }
    const summary = document.createElement("p"); summary.className = "small";
    summary.textContent = `${records.length} accepted historical receipts for ${s.recap.recorded_moment_count} distinct selection moment. No live model calls in this playtest.`;
    container.append(summary);
    for (const receipt of records) {
      const moment = moments.find(row => (row.receipt_ids || []).includes(receipt.receipt_id));
      const article = document.createElement("article"); article.className = "sdk-record";
      const title = document.createElement("h3"); title.textContent = "Historical accepted selection"; article.append(title);
      const values = [
        ["Model", receipt.model_id || "Historical local model"],
        ["Framework", Object.entries(receipt.sdk_versions || {}).map(([key, value]) => `${key} ${value}`).join("; ")],
        ["Selected evidence", moment?.selection ? `${moment.selection.explanation_type}: ${moment.selection.evidence_ids.join(", ")}` : "See source event records"],
        ["Original replay time", `${receipt.through_ms / 1000}s`]
      ];
      for (const [label, value] of values) { const p = document.createElement("p"); const strong = document.createElement("strong"); strong.textContent = label + ": "; p.append(strong, document.createTextNode(value)); article.append(p); }
      container.append(article);
    }
  }
  function renderCard() {
    if (!current) return;
    const p = current.publication;
    const expired = Date.now() >= p.expires_at_ms || performance.now() >= publicationDeadline;
    const signature = JSON.stringify({ text: p.card.text, language: p.card.language, translation: p.card.translation_en, fallback: p.card.fallback, expired, online });
    if (signature === cardFingerprint) return;
    cardFingerprint = signature;
    setText("preview-kind", expired ? "Publication expired" : p.card.fallback ? "Verified facts" : "Recorded selection");
    const card = byId("preview-content");
    card.hidden = expired;
    if (expired) { setText("preview-status", "Expired content has cleared. The score above retains the last confirmed facts. Wait for the replay service to reconnect."); return; }
    setText("card-text", p.card.text);
    byId("card-text").lang = p.card.language;
    const translation = p.card.language === "es" && p.card.translation_en;
    byId("card-translation").hidden = !translation;
    setText("card-translation", translation ? "English: " + p.card.translation_en : "");
    setText("preview-status", online
      ? p.card.fallback ? "Deterministic verified facts. No accepted model explanation is current." : "Accepted historical model selection replayed against matching facts. No live inference."
      : "This is the last confirmed publication. It will clear when its bounded lifetime expires.");
  }
  function render(s) {
    if (!s?.publication?.card || !s.envelope?.provenance || !s.recap?.views) throw new Error("Replay response is incomplete.");
    if (retiredStreams.has(s.publication.stream_id)) return;
    if (current && current.publication.stream_id !== s.publication.stream_id) {
      retiredStreams.add(current.publication.stream_id);
      while (retiredStreams.size > 16) retiredStreams.delete(retiredStreams.values().next().value);
    }
    const identity = `${s.publication.stream_id}:${s.publication.sequence}`;
    if (identity !== publicationIdentity) {
      publicationIdentity = identity;
      const lifetime = Math.max(0, Math.min(30000, s.publication.expires_at_ms - s.publication.issued_at_ms, s.publication.expires_at_ms - Date.now()));
      publicationDeadline = performance.now() + lifetime;
    }
    current = s; online = true; confirmedAt = Date.now(); syncGuidedProgress(s);
    updateFreshness();
    const through = s.publication.event_time.through_ms;
    setText("clock", "Replay time " + Math.floor(through / 60000) + ":" + String(Math.floor(through / 1000) % 60).padStart(2, "0"));
    setText("score", Object.entries(s.publication.facts.score).map(([name, goals]) => `${name} ${goals}`).join(" · "));
    const mode = s.recorded_replay?.status;
    setText("mode", mode === "injected_timeout" ? "Injected timeout · verified facts remain" : mode === "recovered_fallback" ? "Saved replay reopened · old selection discarded" : s.publication.card.fallback ? "Deterministic facts · no live model calls" : "Recorded model selection · no live inference");
    byId("audience").value = s.audience;
    byId("language").value = s.language;
    renderCorrections(s); renderEvidence(s); renderSdk(s); renderCard(); renderFanCorrection(s);
    copyAwaitingState = false; renderCopyReview(s);
    byId("recap-panel").hidden = s.position !== s.positions - 1;
    setText("recap-text", s.recap.views[s.audience][s.language]); byId("recap-text").lang = s.language;
    byId("recap-translation").hidden = s.language !== "es";
    setText("recap-english", s.language === "es" ? s.recap.views[s.audience].en : "");
    setText("recap-proof", `${s.recap.withdrawn_claims.length} withdrawn goal claim. ${s.recap.recorded_receipt_count} historical accepted receipts / ${s.recap.recorded_moment_count} distinct moment.`);
    updateControls();
    showSessionLimits();
  }
  async function control(command, { primary = false } = {}) {
    if (busy || copyAwaitingState || !authenticated || !online) return;
    copyInUse = ["review_copy", "approve_copy", "clear_copy"].includes(command.action);
    busy = true; generation++; publicIssue = ""; updateControls(); say("");
    setText("action-status", "Updating your replay…");
    try {
      const s = await request("/api/control", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ ...command, operation_id: idempotencyId() }) });
      render(s);
      if (["new_match", "reset"].includes(command.action)) {
        inspected = false;
        copyInUse = false; syncGuidedProgress(s);
      }
      const messages = { pattern: "50-second moment shown.", replay3: "Accepted historical selection replayed. No model call was made.", correct: "Goal correction applied. Inspect the change above.", timeout: "Simulated timeout. Active advice and draft approval cleared; checked facts remain available.", recover: "Saved replay reopened. Committed facts remain; the selected card is discarded. Review the current sample again to resume the guide.", finish: "Final corrected recap is ready below.", reset: "Replay rewound. Approved corrections remain.", new_match: "A fresh synthetic match is ready. The previous journal was archived.", view: "Presentation updated. Verified facts stay the same.", review_copy: "Recorded producer-copy review loaded. No model call was made.", approve_copy: "Producer draft saved in your session; not transmitted. Broadcast preview unchanged.", clear_copy: "Producer-copy review cleared. Broadcast preview unchanged." };
      setText("action-status", messages[command.action] || "Replay updated.");
      if (command.action === "recover" && s.position === s.positions - 1) {
        setText("action-status", "Saved replay reopened at the final moment. The corrected recap is ready below. Rewind keeps corrections if you want to review the 50-second copy again.");
      }
      const regions = { pattern: "preview-title", replay3: "preview-title", correct: "correction-title", review_copy: "copy-decision", approve_copy: "copy-approved-title", clear_copy: "copy-title", finish: "recap-title", timeout: byId("copy-recovery-result").hidden ? "preview-title" : "copy-recovery-title", recover: "score-title", reset: "score-title", new_match: "score-title", view: "preview-title" };
      revealResult(command.action === "recover" && s.position === s.positions - 1 ? "recap-title" : regions[command.action] || "score-title", primary);
      if (command.action === "new_match") { inspected = false; if (Number.isInteger(matchesUsed)) matchesUsed++; byId("evidence-panel").hidden = true; byId("inspect-evidence").setAttribute("aria-expanded", "false"); }
    } catch (error) {
      if (current?.copy_review || ["review_copy", "approve_copy", "clear_copy"].includes(command.action)) copyAwaitingState = true;
      if ([401, 403].includes(error.status)) expireSession();
      else {
        if (!error.status || error.status >= 500) { online = false; updateFreshness(); renderCard(); }
        const message = error.name === "AbortError" || (error.name === "TypeError" && !error.status)
          ? "The response was not confirmed; the action's outcome is uncertain. Wait for the refreshed facts before trying again."
          : error.message;
        say(message, true); publicIssue = message;
      }
      setText("action-status", "Action not confirmed. Check the latest facts before repeating it.");
    } finally { busy = false; updateControls(); showSessionLimits(); }
  }
  document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => control({ action: button.dataset.action })));
  byId("next-action").addEventListener("click", runNextAction);
  for (const id of ["audience", "language"]) byId(id).addEventListener("change", () => control({ action: "view", audience: byId("audience").value, language: byId("language").value }));
  byId("copy-case")?.addEventListener("change", () => { copyInUse = true; updateCopyControls(); });
  byId("copy-review")?.addEventListener("focusin", () => { if (!copyInUse) { copyInUse = true; updateCopyControls(); } });
  byId("copy-review-button")?.addEventListener("click", () => { if (canReviewCopy()) { copyInUse = true; return control({ action: "review_copy", case_id: selectedCopyCase().case_id }); } });
  byId("copy-approve")?.addEventListener("click", () => { if (canApproveCopy()) { copyInUse = true; return control({ action: "approve_copy", advice_id: current.copy_review.advice.advice_id }); } });
  byId("copy-clear")?.addEventListener("click", () => { if (!byId("copy-clear").disabled) return control({ action: "clear_copy" }); });
  byId("inspect-evidence").addEventListener("click", () => {
    const panel = byId("evidence-panel"); panel.hidden = !panel.hidden;
    byId("inspect-evidence").setAttribute("aria-expanded", String(!panel.hidden));
    inspected = inspected || !panel.hidden; updateControls();
    setText("action-status", panel.hidden ? "Evidence panel closed." : "Evidence panel opened below the steps.");
    if (!panel.hidden) revealResult("evidence-title");
  });
  byId("new-match").addEventListener("click", () => { byId("new-match-confirmation").hidden = false; byId("new-match-cancel").focus(); });
  byId("new-match-cancel").addEventListener("click", () => { byId("new-match-confirmation").hidden = true; byId("new-match").focus(); });
  byId("new-match-confirm").addEventListener("click", async () => { byId("new-match-confirmation").hidden = true; await control({ action: "new_match" }); byId("new-match").focus(); });
  byId("logout").addEventListener("click", async () => {
    try { if (authenticated) await request("/api/logout", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: "{}" }); }
    catch (_) { say("Sign-out could not be confirmed. Close this tab and try again when the service returns.", true); return; }
    window.location.assign("/");
  });
  byId("feedback-comment").addEventListener("input", () => setText("comment-count", byId("feedback-comment").value.length.toLocaleString() + " / 1,000 characters"));
  byId("feedback-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = byId("feedback-form");
    if (feedbackBusy || !form.reportValidity() || !authenticated) return;
    feedbackBusy = true; updateControls(); setText("feedback-status", "Sending privately…");
    byId("feedback-status").classList.remove("error", "feedback-success");
    const ratings = Object.fromEntries(["clarity", "usefulness", "trust"].map(key => [key, Number(byId("rating-" + key).value)]));
    try {
      const payload = { consent: byId("feedback-consent").checked, ratings, role: byId("feedback-role").value, comment: byId("feedback-comment").value.trim() };
      const fingerprint = JSON.stringify(payload);
      if (!feedbackAttempt || feedbackAttempt.fingerprint !== fingerprint) feedbackAttempt = { fingerprint, feedback_id: idempotencyId(), viewport: window.innerWidth < 650 ? "phone" : window.innerWidth < 1024 ? "tablet" : "desktop" };
      const receipt = await request("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ ...payload, viewport: feedbackAttempt.viewport, feedback_id: feedbackAttempt.feedback_id }) });
      if (receipt.saved !== true || typeof receipt.receipt_id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(receipt.receipt_id)) throw new Error("Feedback receipt was not confirmed. Your draft and attempt ID are retained; retrying unchanged feedback will reuse that ID.");
      byId("feedback-receipt").hidden = false;
      setText("feedback-receipt", `Last confirmed receipt: ${receipt.receipt_id}${receipt.duplicate === true ? ". Earlier receipt confirmed; no duplicate feedback was stored." : ". Private feedback received."}`);
      form.reset(); feedbackAttempt = null; setText("comment-count", "0 / 1,000 characters");
      setText("feedback-status", "Your private feedback was received. Thank you for checking the replay."); byId("feedback-status").classList.add("feedback-success");
    } catch (error) {
      setText("feedback-status", error.status === 410 ? "That earlier feedback was deleted and was not stored again. Edit your draft to make a new submission." : error.status === 409 ? "This feedback attempt differs from its earlier payload. Your draft is retained; check it before making a new submission." : error.name === "AbortError" ? "The feedback response timed out; receipt is uncertain. Your draft and attempt ID are retained. Retrying unchanged feedback uses the same ID to avoid a duplicate." : error.message);
      byId("feedback-status").classList.add("error");
      if ([401, 403].includes(error.status)) expireSession();
    } finally { feedbackBusy = false; updateControls(); }
  });
  byId("feedback-delete").addEventListener("click", () => { byId("feedback-delete-confirmation").hidden = false; byId("feedback-delete-cancel").focus(); });
  byId("feedback-delete-cancel").addEventListener("click", () => { byId("feedback-delete-confirmation").hidden = true; byId("feedback-delete").focus(); });
  byId("feedback-delete-confirm").addEventListener("click", async () => {
    if (!authenticated || feedbackBusy) return;
    feedbackBusy = true; updateControls(); setText("feedback-delete-status", "Deleting this session's feedback…");
    try {
      await request("/api/feedback", { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
      byId("feedback-delete-confirmation").hidden = true;
      setText("feedback-delete-status", "Feedback from this session was deleted.");
    } catch (error) { setText("feedback-delete-status", error.message); if ([401, 403].includes(error.status)) expireSession(); }
    finally { feedbackBusy = false; updateControls(); byId("feedback-delete").focus(); }
  });
  async function poll() {
    if (authenticated && !busy && !document.hidden) {
      const observedGeneration = generation;
      try {
        const s = await request("/api/state");
        if (!busy && observedGeneration === generation && authenticated) {
          const compatible = !current || s.publication.stream_id !== current.publication.stream_id || s.publication.sequence >= current.publication.sequence;
          if (compatible) { render(s); if (publicIssue) say(publicIssue, true); else say(""); }
        }
      } catch (error) {
        if (observedGeneration === generation && !busy) {
          if ([401, 403].includes(error.status)) expireSession();
          else { online = false; updateFreshness(); updateControls(); renderCard(); say(error.status === 429 ? error.message : "Replay service unavailable. The score is the last confirmed state; expired preview content clears automatically.", true); }
        }
      }
    }
    setTimeout(poll, 4000);
  }
  async function init() {
    updateControls();
    try {
      const session = await request("/api/session");
      if (!session.authenticated || typeof session.csrf !== "string") { expireSession(); return; }
      authenticated = true; csrf = session.csrf;
      const s = await request("/api/state"); render(s);
      maxMatches = Number.isInteger(session.max_matches) ? session.max_matches : 3;
      matchesUsed = Number.isInteger(session.matches_used) ? session.matches_used : null;
      showSessionLimits();
    } catch (error) {
      online = false; updateFreshness(); updateControls();
      say(error.name === "AbortError" ? "The playtest took too long to connect. Refresh this page when the service returns." : error.message, true);
    }
    poll();
  }
  setInterval(renderCard, 500);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) renderCard(); });
  init();
})();
