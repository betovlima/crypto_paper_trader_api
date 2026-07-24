import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  createExperiment as createExperimentRequest,
  getExperiment,
  getRunningExperimentHeaderSummary,
  listExperimentHistory,
  retryAdaptiveSelectorHistory,
  retryAdaptiveSelectorResearch,
  stopRunningExperiment,
} from "./api/experimentsApi";
import {
  getStrategyComparison,
  listStrategyAccounts,
} from "./api/strategyApi";
import { getPublicConfiguration } from "./api/systemApi";
import {
  getAIOpportunityScannerStatus,
  listLatestAIOpportunities,
} from "./api/aiOpportunitiesApi";
import {
  detectInitialLanguage,
  INTL_LOCALES,
  translate,
  translateDynamicText,
} from "./i18n";

import {
  AI_OPPORTUNITY_CARD_LIMIT, AI_SCANNER_REFRESH_MS, APP_VERSION,
  LANGUAGE_STORAGE_KEY, PINNED_STRATEGY_CODE, REFRESH_SECONDS,
  SELECTED_EXPERIMENT_STORAGE_KEY, STRATEGY_ORDER_STORAGE_KEY, STRATEGY_VISUALS,
} from "./config/dashboard";
import {
  formatMarketPair, formatTime, normalizeMarketSymbol, readStoredStrategyOrder, sameRows, setStable,
  strategyAutomaticPriority, strategyOpenPositionUrgency,
} from "./shared/dashboardUtils";
import { StrategyCard } from "./features/strategies/StrategyCard";
import { AIOpportunityScannerPanel } from "./features/opportunities/AIOpportunityScannerPanel";
import { SetupDialog, StopDialog, HistoryRetryDialog, ResearchRetryDialog } from "./features/experiments/ExperimentDialogs";
import { LanguageSelector, RunningExperimentTopbarSummary, ExperimentCycleBar } from "./components/layout/DashboardHeader";

export default function App() {
  const [language, setLanguage] = useState(detectInitialLanguage);
  const [configuration, setConfiguration] = useState(null);
  const [experiments, setExperiments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [runningHeaderSummary, setRunningHeaderSummary] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [decisionsByStrategy, setDecisionsByStrategy] = useState({});
  const [strategyOrder, setStrategyOrder] = useState(readStoredStrategyOrder);
  const [dragPreviewOrder, setDragPreviewOrder] = useState(null);
  const [draggedStrategyCode, setDraggedStrategyCode] = useState(null);
  const [draggedCardHeight, setDraggedCardHeight] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [lastFrontendRefresh, setLastFrontendRefresh] = useState(null);
  const [isConfigurationOpen, setIsConfigurationOpen] = useState(false);
  const [isStopOpen, setIsStopOpen] = useState(false);
  const [adminKey, setAdminKey] = useState("");
  const [stopError, setStopError] = useState("");
  const [stopping, setStopping] = useState(false);
  const [closeOpenPositions, setCloseOpenPositions] = useState(true);
  const [isHistoryRetryOpen, setIsHistoryRetryOpen] = useState(false);
  const [historyAdminKey, setHistoryAdminKey] = useState("");
  const [historyRetryError, setHistoryRetryError] = useState("");
  const [retryingHistory, setRetryingHistory] = useState(false);
  const [isResearchRetryOpen, setIsResearchRetryOpen] = useState(false);
  const [researchAdminKey, setResearchAdminKey] = useState("");
  const [researchRetryError, setResearchRetryError] = useState("");
  const [retryingResearch, setRetryingResearch] = useState(false);
  const [aiScannerStatus, setAiScannerStatus] = useState(null);
  const [aiOpportunities, setAiOpportunities] = useState([]);
  const [form, setForm] = useState({
    market: "",
    duration_hours: 24,
    initial_capital: 1000,
    trading_profile: "BALANCED_INTRADAY",
  });

  const selectedIdRef = useRef(window.localStorage.getItem(SELECTED_EXPERIMENT_STORAGE_KEY) || null);
  const refreshInFlightRef = useRef(false);
  const scannerRefreshInFlightRef = useRef(false);
  const lastScannerCompletionRef = useRef(null);
  const mountedRef = useRef(true);
  const strategiesGridRef = useRef(null);
  const dragSessionRef = useRef(null);
  const dragPreviewOrderRef = useRef(null);
  const dragFrameRef = useRef(null);
  const strategyFlipRectsRef = useRef(new Map());
  const strategyFlipAnimationsRef = useRef(new Map());
  const t = useCallback((source) => translate(language, source), [language]);

  useEffect(() => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    document.documentElement.lang = INTL_LOCALES[language] || "en-US";
    document.title = "Crypto Paper Trader";
  }, [language]);

  const refresh = useCallback(async ({ includeConfiguration = false } = {}) => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;

    try {
      const requests = [
        listExperimentHistory({ page: 1, page_size: 20, sort_direction: "desc" }),
        getRunningExperimentHeaderSummary(),
        getAIOpportunityScannerStatus(),
        listLatestAIOpportunities(AI_OPPORTUNITY_CARD_LIMIT),
      ];
      if (includeConfiguration) requests.unshift(getPublicConfiguration());

      const payload = await Promise.all(requests);
      const offset = includeConfiguration ? 1 : 0;
      const config = includeConfiguration ? payload[0] : null;
      const historyPayload = payload[offset];
      const headerSummary = payload[offset + 1];
      const scannerStatus = payload[offset + 2];
      const opportunityRows = payload[offset + 3] || [];
      const list = historyPayload.items || [];

      if (!mountedRef.current) return;
      if (config) setStable(setConfiguration, config);
      setStable(setExperiments, list, sameRows);
      setStable(setRunningHeaderSummary, headerSummary);
      setStable(setAiScannerStatus, scannerStatus);
      setStable(setAiOpportunities, opportunityRows, sameRows);
      if (scannerStatus?.last_scan_completed_at) {
        lastScannerCompletionRef.current = scannerStatus.last_scan_completed_at;
      }

      let currentId = selectedIdRef.current;
      if (currentId && !list.some((item) => item.id === currentId)) currentId = null;
      currentId ||= list[0]?.id;

      if (currentId) {
        selectedIdRef.current = currentId;
        window.localStorage.setItem(SELECTED_EXPERIMENT_STORAGE_KEY, currentId);

        const [detail, strategyRows, comparison] = await Promise.all([
          getExperiment(currentId),
          listStrategyAccounts(currentId),
          getStrategyComparison(currentId),
        ]);
        if (!mountedRef.current) return;

        const decisionMap = Object.fromEntries(
          (comparison?.strategies || []).map((item) => [item.strategy_code, item.latest_decision || null]),
        );

        setStable(setSelected, detail);
        setStable(setStrategies, strategyRows || [], sameRows);
        setStable(setDecisionsByStrategy, decisionMap);
      } else {
        selectedIdRef.current = null;
        window.localStorage.removeItem(SELECTED_EXPERIMENT_STORAGE_KEY);
        setSelected(null);
        setStrategies([]);
        setDecisionsByStrategy({});
      }

      setLastFrontendRefresh(Date.now());
      setError("");
    } catch (err) {
      if (err?.status === 404 && selectedIdRef.current) {
        selectedIdRef.current = null;
        window.localStorage.removeItem(SELECTED_EXPERIMENT_STORAGE_KEY);
      }
      if (mountedRef.current) setError(translateDynamicText(language, err.message || "Unable to refresh the application."));
    } finally {
      refreshInFlightRef.current = false;
      if (mountedRef.current) setLoading(false);
    }
  }, [language]);

  const refreshScannerStatus = useCallback(async () => {
    if (scannerRefreshInFlightRef.current || document.hidden) return;
    scannerRefreshInFlightRef.current = true;

    try {
      const scannerStatus = await getAIOpportunityScannerStatus();
      if (!mountedRef.current) return;
      setStable(setAiScannerStatus, scannerStatus);

      const completedAt = scannerStatus?.last_scan_completed_at || null;
      if (completedAt && completedAt !== lastScannerCompletionRef.current) {
        const opportunityRows = await listLatestAIOpportunities(AI_OPPORTUNITY_CARD_LIMIT);
        if (!mountedRef.current) return;
        lastScannerCompletionRef.current = completedAt;
        setStable(setAiOpportunities, opportunityRows || [], sameRows);
      }
    } catch {
      // The regular application refresh displays connection errors. This short
      // polling loop remains silent to avoid flashing the whole dashboard.
    } finally {
      scannerRefreshInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    const timer = window.setInterval(refreshScannerStatus, AI_SCANNER_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refreshScannerStatus]);

  useEffect(() => {
    mountedRef.current = true;
    refresh({ includeConfiguration: true });
    const timer = window.setInterval(() => refresh(), REFRESH_SECONDS * 1000);
    return () => {
      mountedRef.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (!configuration) return;
    setForm((previous) => ({
      ...previous,
      market: previous.market || formatMarketPair(configuration.default_market),
      duration_hours: previous.duration_hours || configuration.default_duration_hours,
      initial_capital: previous.initial_capital || configuration.default_initial_capital,
      trading_profile: previous.trading_profile || "BALANCED_INTRADAY",
    }));
  }, [configuration]);

  useEffect(() => {
    if (!selected?.market) return;
    setForm((previous) => ({ ...previous, market: formatMarketPair(selected.market) }));
  }, [selected?.id, selected?.market]);


  useEffect(() => {
    const availableCodes = strategies.map((item) => item.strategy_code);
    if (!availableCodes.length) return;

    setStrategyOrder((previous) => {
      const next = [
        ...previous.filter((code) => availableCodes.includes(code)),
        ...availableCodes.filter((code) => !previous.includes(code)),
      ];
      if (next.length === previous.length && next.every((code, index) => code === previous[index])) return previous;
      window.localStorage.setItem(STRATEGY_ORDER_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, [strategies]);

  const effectiveStrategyOrder = dragPreviewOrder || strategyOrder;

  const orderedStrategies = useMemo(() => {
    const orderIndex = new Map(effectiveStrategyOrder.map((code, index) => [code, index]));
    const marketPrice = Number(selected?.last_price || 0);

    return [...strategies].sort((left, right) => {
      const leftDecision = decisionsByStrategy[left.strategy_code];
      const rightDecision = decisionsByStrategy[right.strategy_code];
      const leftPriority = strategyAutomaticPriority(left, leftDecision);
      const rightPriority = strategyAutomaticPriority(right, rightDecision);

      if (leftPriority !== rightPriority) return leftPriority - rightPriority;

      // Among active positions, show the operation needing the most attention first:
      // confirmed exit, armed exit, largest open loss, then oldest position.
      if (leftPriority === 10) {
        const leftUrgency = strategyOpenPositionUrgency(
          left,
          leftDecision,
          marketPrice,
        );
        const rightUrgency = strategyOpenPositionUrgency(
          right,
          rightDecision,
          marketPrice,
        );

        if (leftUrgency.exitAttention !== rightUrgency.exitAttention) {
          return leftUrgency.exitAttention - rightUrgency.exitAttention;
        }
        if (leftUrgency.openReturn !== rightUrgency.openReturn) {
          return leftUrgency.openReturn - rightUrgency.openReturn;
        }
        if (leftUrgency.entryTimestamp !== rightUrgency.entryTimestamp) {
          return leftUrgency.entryTimestamp - rightUrgency.entryTimestamp;
        }
      }

      // The user's saved order remains the final tie-breaker inside the same status.
      const leftIndex = orderIndex.get(left.strategy_code) ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = orderIndex.get(right.strategy_code) ?? Number.MAX_SAFE_INTEGER;
      return leftIndex - rightIndex;
    });
  }, [
    strategies,
    decisionsByStrategy,
    effectiveStrategyOrder,
    selected?.last_price,
  ]);

  const persistStrategyOrder = useCallback((nextOrder) => {
    setStrategyOrder(nextOrder);
    window.localStorage.setItem(STRATEGY_ORDER_STORAGE_KEY, JSON.stringify(nextOrder));
  }, []);

  const moveStrategyByOffset = useCallback((strategyCode, offset) => {
    if (strategyCode === PINNED_STRATEGY_CODE) return;

    const current = orderedStrategies.map((item) => item.strategy_code);
    const sourceIndex = current.indexOf(strategyCode);
    if (sourceIndex < 0) return;

    const firstMovableIndex = current[0] === PINNED_STRATEGY_CODE ? 1 : 0;
    const targetIndex = Math.max(
      firstMovableIndex,
      Math.min(current.length - 1, sourceIndex + offset),
    );
    if (sourceIndex === targetIndex) return;

    const next = [...current];
    const [moved] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, moved);
    persistStrategyOrder(next);
  }, [orderedStrategies, persistStrategyOrder]);

  const captureStrategyCardPositions = useCallback(() => {
    const grid = strategiesGridRef.current;
    if (!grid) return;

    const nextRects = new Map();
    grid.querySelectorAll("[data-strategy-key]").forEach((element) => {
      nextRects.set(element.dataset.strategyKey, element.getBoundingClientRect());
    });
    strategyFlipRectsRef.current = nextRects;
  }, []);

  const setDragPreview = useCallback((nextOrder) => {
    captureStrategyCardPositions();
    dragPreviewOrderRef.current = nextOrder;
    setDragPreviewOrder(nextOrder);
  }, [captureStrategyCardPositions]);

  useLayoutEffect(() => {
    if (!draggedStrategyCode || !dragPreviewOrder) return;

    const grid = strategiesGridRef.current;
    const previousRects = strategyFlipRectsRef.current;
    if (!grid || !previousRects.size) return;

    const liveKeys = new Set();
    grid.querySelectorAll("[data-strategy-key]").forEach((element) => {
      const key = element.dataset.strategyKey;
      liveKeys.add(key);
      const previous = previousRects.get(key);
      if (!previous) return;

      const current = element.getBoundingClientRect();
      const deltaX = previous.left - current.left;
      const deltaY = previous.top - current.top;
      if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) return;

      strategyFlipAnimationsRef.current.get(key)?.cancel();
      const animation = element.animate(
        [
          { transform: `translate3d(${deltaX}px, ${deltaY}px, 0)` },
          { transform: "translate3d(0, 0, 0)" },
        ],
        {
          duration: 230,
          easing: "cubic-bezier(0.22, 1, 0.36, 1)",
          fill: "both",
        },
      );
      strategyFlipAnimationsRef.current.set(key, animation);
      animation.onfinish = () => {
        if (strategyFlipAnimationsRef.current.get(key) === animation) {
          strategyFlipAnimationsRef.current.delete(key);
        }
      };
      animation.oncancel = animation.onfinish;
    });

    Array.from(strategyFlipAnimationsRef.current.keys()).forEach((key) => {
      if (!liveKeys.has(key)) {
        strategyFlipAnimationsRef.current.get(key)?.cancel();
        strategyFlipAnimationsRef.current.delete(key);
      }
    });

    strategyFlipRectsRef.current = new Map(
      Array.from(grid.querySelectorAll("[data-strategy-key]")).map((element) => [
        element.dataset.strategyKey,
        element.getBoundingClientRect(),
      ]),
    );
  }, [dragPreviewOrder, draggedStrategyCode]);

  const removeDragGhost = useCallback(() => {
    const session = dragSessionRef.current;
    if (session?.ghost?.parentNode) session.ghost.parentNode.removeChild(session.ghost);
    document.body.classList.remove("is-reordering-strategies");
  }, []);

  const finishStrategyDrag = useCallback((commit = true) => {
    const session = dragSessionRef.current;
    if (!session) return;

    if (dragFrameRef.current) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = null;
    }

    window.removeEventListener("pointermove", session.handlePointerMove);
    window.removeEventListener("pointerup", session.handlePointerUp);
    window.removeEventListener("pointercancel", session.handlePointerCancel);
    window.removeEventListener("keydown", session.handleKeyDown);

    if (commit && dragPreviewOrderRef.current) {
      persistStrategyOrder(dragPreviewOrderRef.current);
    }

    removeDragGhost();
    strategyFlipAnimationsRef.current.forEach((animation) => animation.cancel());
    strategyFlipAnimationsRef.current.clear();
    strategyFlipRectsRef.current.clear();
    dragSessionRef.current = null;
    dragPreviewOrderRef.current = null;
    setDragPreviewOrder(null);
    setDraggedStrategyCode(null);
    setDraggedCardHeight(0);
  }, [persistStrategyOrder, removeDragGhost]);

  const calculateDropOrder = useCallback((clientX, clientY, sourceCode) => {
    const grid = strategiesGridRef.current;
    const currentOrder = dragPreviewOrderRef.current;
    if (!grid || !currentOrder?.length) return currentOrder;

    const cards = Array.from(
      grid.querySelectorAll(".strategy-card[data-strategy-code]"),
    ).filter((card) => card instanceof HTMLElement);
    const nonDraggedOrder = currentOrder.filter((code) => code !== sourceCode);
    if (!cards.length || !nonDraggedOrder.length) return currentOrder;

    /** @type {HTMLElement | null} */
    let targetElement = null;
    let closestDistance = Number.POSITIVE_INFINITY;

    for (const card of cards) {
      const rect = card.getBoundingClientRect();
      const dx = clientX < rect.left ? rect.left - clientX : clientX > rect.right ? clientX - rect.right : 0;
      const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
      const distance = Math.hypot(dx, dy);
      if (distance < closestDistance) {
        closestDistance = distance;
        targetElement = card;
      }
    }

    if (!targetElement) return currentOrder;

    const targetCode = targetElement.dataset.strategyCode;
    const targetIndex = nonDraggedOrder.indexOf(targetCode);
    if (targetIndex < 0) return currentOrder;

    const rect = targetElement.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const verticalBias = Math.abs(clientY - centerY) > rect.height * 0.2;
    const insertAfter = verticalBias ? clientY > centerY : clientX > centerX;
    const insertionIndex = targetIndex + (insertAfter ? 1 : 0);

    const next = [...nonDraggedOrder];
    const minimumInsertionIndex = next[0] === PINNED_STRATEGY_CODE ? 1 : 0;
    next.splice(Math.max(minimumInsertionIndex, insertionIndex), 0, sourceCode);

    const pinnedIndex = next.indexOf(PINNED_STRATEGY_CODE);
    if (pinnedIndex > 0) {
      next.splice(pinnedIndex, 1);
      next.unshift(PINNED_STRATEGY_CODE);
    }

    return next;
  }, []);

  const startStrategyDrag = useCallback((event, strategyCode) => {
    if (
      strategyCode === PINNED_STRATEGY_CODE
      || event.button !== 0
      || dragSessionRef.current
    ) return;

    const card = event.currentTarget.closest(".strategy-card");
    if (!card) return;

    event.preventDefault();
    event.stopPropagation();

    const rect = card.getBoundingClientRect();
    const ghost = card.cloneNode(true);
    ghost.classList.add("strategy-drag-ghost");
    ghost.classList.remove("is-dragging");
    ghost.setAttribute("aria-hidden", "true");
    ghost.style.width = `${rect.width}px`;
    ghost.style.height = `${rect.height}px`;
    ghost.style.left = "0";
    ghost.style.top = "0";
    ghost.style.transform = `translate3d(${rect.left}px, ${rect.top}px, 0)`;
    ghost.querySelectorAll("button").forEach((button) => {
      button.tabIndex = -1;
      button.disabled = true;
    });
    document.body.appendChild(ghost);
    document.body.classList.add("is-reordering-strategies");

    const initialOrder = orderedStrategies.map((item) => item.strategy_code);
    setDragPreview(initialOrder);
    setDraggedStrategyCode(strategyCode);
    setDraggedCardHeight(rect.height);

    const session = {
      code: strategyCode,
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      ghost,
      lastPointer: { x: event.clientX, y: event.clientY },
      handlePointerMove: null,
      handlePointerUp: null,
      handlePointerCancel: null,
      handleKeyDown: null,
    };

    const processPointer = () => {
      dragFrameRef.current = null;
      const active = dragSessionRef.current;
      if (!active) return;

      const { x, y } = active.lastPointer;
      active.ghost.style.transform = `translate3d(${x - active.offsetX}px, ${y - active.offsetY}px, 0)`;

      const nextOrder = calculateDropOrder(x, y, active.code);
      const currentOrder = dragPreviewOrderRef.current;
      if (
        nextOrder
        && currentOrder
        && (nextOrder.length !== currentOrder.length || nextOrder.some((code, index) => code !== currentOrder[index]))
      ) {
        setDragPreview(nextOrder);
      }

      const edge = 88;
      const maximumStep = 22;
      let scrollStep = 0;
      if (y < edge) scrollStep = -Math.ceil(maximumStep * (1 - Math.max(0, y) / edge));
      if (y > window.innerHeight - edge) {
        scrollStep = Math.ceil(maximumStep * (1 - Math.max(0, window.innerHeight - y) / edge));
      }
      if (scrollStep) window.scrollBy(0, scrollStep);
    };

    session.handlePointerMove = (pointerEvent) => {
      if (pointerEvent.pointerId !== session.pointerId) return;
      pointerEvent.preventDefault();
      session.lastPointer = { x: pointerEvent.clientX, y: pointerEvent.clientY };
      if (!dragFrameRef.current) dragFrameRef.current = window.requestAnimationFrame(processPointer);
    };
    session.handlePointerUp = (pointerEvent) => {
      if (pointerEvent.pointerId !== session.pointerId) return;
      const finalOrder = calculateDropOrder(pointerEvent.clientX, pointerEvent.clientY, session.code);
      if (finalOrder) setDragPreview(finalOrder);
      finishStrategyDrag(true);
    };
    session.handlePointerCancel = (pointerEvent) => {
      if (pointerEvent.pointerId !== session.pointerId) return;
      finishStrategyDrag(false);
    };
    session.handleKeyDown = (keyboardEvent) => {
      if (keyboardEvent.key !== "Escape") return;
      keyboardEvent.preventDefault();
      finishStrategyDrag(false);
    };

    dragSessionRef.current = session;
    window.addEventListener("pointermove", session.handlePointerMove, { passive: false });
    window.addEventListener("pointerup", session.handlePointerUp);
    window.addEventListener("pointercancel", session.handlePointerCancel);
    window.addEventListener("keydown", session.handleKeyDown);
  }, [calculateDropOrder, finishStrategyDrag, orderedStrategies, setDragPreview]);

  useEffect(() => () => {
    if (dragSessionRef.current) finishStrategyDrag(false);
  }, [finishStrategyDrag]);

  const selectProfile = (profileCode) => {
    const profile = configuration?.trading_profiles?.find((item) => item.code === profileCode);
    setForm((previous) => ({
      ...previous,
      trading_profile: profileCode,
      duration_hours: profile?.default_duration_hours ?? previous.duration_hours,
    }));
  };

  const createExperiment = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const created = await createExperimentRequest({
        ...form,
        market: normalizeMarketSymbol(form.market),
        duration_hours: Number(form.duration_hours),
        initial_capital: Number(form.initial_capital),
      });
      selectedIdRef.current = created.id;
      window.localStorage.setItem(SELECTED_EXPERIMENT_STORAGE_KEY, created.id);
      setSelected(created);
      setIsConfigurationOpen(false);
      await refresh();
    } catch (err) {
      setError(translateDynamicText(language, err.message || "Unable to start the simulation."));
    } finally {
      setSaving(false);
    }
  };


  const openConfiguration = () => {
    setIsConfigurationOpen(true);
  };

  const closeConfiguration = () => {
    if (saving) return;
    setIsConfigurationOpen(false);
  };

  const openStopDialog = () => {
    setAdminKey("");
    setStopError("");
    setCloseOpenPositions(true);
    setIsStopOpen(true);
  };

  const closeStopDialog = () => {
    if (stopping) return;
    setAdminKey("");
    setStopError("");
    setCloseOpenPositions(true);
    setIsStopOpen(false);
  };

  const confirmStop = async (event) => {
    event.preventDefault();
    setStopping(true);
    setStopError("");
    try {
      await stopRunningExperiment({
        adminKey: adminKey.trim(),
        closeOpenPositions,
      });
      setIsStopOpen(false);
      setAdminKey("");
      await refresh({ includeConfiguration: true });
    } catch (err) {
      setStopError(translateDynamicText(language, err.message || "Unable to stop the running experiment."));
    } finally {
      setStopping(false);
    }
  };

  const openHistoryRetryDialog = () => {
    setHistoryAdminKey("");
    setHistoryRetryError("");
    setIsHistoryRetryOpen(true);
  };

  const closeHistoryRetryDialog = () => {
    if (retryingHistory) return;
    setHistoryAdminKey("");
    setHistoryRetryError("");
    setIsHistoryRetryOpen(false);
  };

  const confirmHistoryRetry = async (event) => {
    event.preventDefault();
    if (!selected?.id) return;
    setRetryingHistory(true);
    setHistoryRetryError("");
    try {
      await retryAdaptiveSelectorHistory({
        experimentId: selected.id,
        adminKey: historyAdminKey.trim(),
      });
      setIsHistoryRetryOpen(false);
      setHistoryAdminKey("");
      await refresh();
    } catch (err) {
      setHistoryRetryError(
        translateDynamicText(language, err.message || "Unable to retry adaptive history."),
      );
    } finally {
      setRetryingHistory(false);
    }
  };

  const openResearchRetryDialog = () => {
    setResearchAdminKey("");
    setResearchRetryError("");
    setIsResearchRetryOpen(true);
  };

  const closeResearchRetryDialog = () => {
    if (retryingResearch) return;
    setResearchAdminKey("");
    setResearchRetryError("");
    setIsResearchRetryOpen(false);
  };

  const confirmResearchRetry = async (event) => {
    event.preventDefault();
    if (!selected?.id) return;
    setRetryingResearch(true);
    setResearchRetryError("");
    try {
      await retryAdaptiveSelectorResearch({
        experimentId: selected.id,
        adminKey: researchAdminKey.trim(),
      });
      setIsResearchRetryOpen(false);
      setResearchAdminKey("");
      await refresh();
    } catch (err) {
      setResearchRetryError(
        translateDynamicText(language, err.message || "Unable to retry adaptive research."),
      );
    } finally {
      setRetryingResearch(false);
    }
  };

  useLayoutEffect(() => {
    if (!isConfigurationOpen) return undefined;

    const body = document.body;
    const previousOverflow = body.style.overflow;
    const previousPaddingRight = body.style.paddingRight;
    const computedPaddingRight = Number.parseFloat(window.getComputedStyle(body).paddingRight) || 0;
    const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth);

    if (scrollbarWidth > 0) {
      body.style.paddingRight = `${computedPaddingRight + scrollbarWidth}px`;
    }
    body.style.overflow = "hidden";

    return () => {
      body.style.overflow = previousOverflow;
      body.style.paddingRight = previousPaddingRight;
    };
  }, [isConfigurationOpen]);

  useEffect(() => {
    if (!isConfigurationOpen && !isStopOpen) return undefined;

    const handleKeyDown = (event) => {
      if (event.key !== "Escape") return;

      if (isStopOpen && !stopping) {
        closeStopDialog();
        return;
      }

      if (isConfigurationOpen && !saving) {
        setIsConfigurationOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isConfigurationOpen, isStopOpen, stopping, saving]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className={`topbar-inner${runningHeaderSummary?.visible ? " has-running-context" : ""}`}>
          <div className="brand-block">
            <img className="brand-mark" src="/app-icon.png" alt="" aria-hidden="true" />
            <div>
              <span className="eyebrow">{t("MEXC Spot · Paper Trading")}</span>
              <div className="brand-title-row">
                <h1>Crypto Paper Trader</h1>
                <span className="version-badge">v{APP_VERSION}</span>
              </div>
            </div>
          </div>

          <RunningExperimentTopbarSummary
            summary={runningHeaderSummary}
            t={t}
          />

          <div className="topbar-actions">
            <LanguageSelector language={language} onChange={setLanguage} t={t} />
            <button type="button" className="secondary-button" onClick={openConfiguration}>
              {t("Setup")}
            </button>
          </div>
        </div>
      </header>

      <ExperimentCycleBar summary={runningHeaderSummary} t={t} />

      {error && <div className="alert" role="alert">{error}</div>}

      <main className="workspace">
        <section className="dashboard-column">
          <AIOpportunityScannerPanel
            status={aiScannerStatus}
            opportunities={aiOpportunities}
            language={language}
            t={t}
          />

          {!selected ? (
            <section className="welcome-card">
              <span>{t("Ready")}</span>
              <h2>{t("Start a paper-trading experiment")}</h2>
              <p>{t("Choose an asset and start the simulation.")}</p>
              <button type="button" className="primary-button welcome-action" onClick={openConfiguration}>{t("Open setup")}</button>
            </section>
          ) : (
            <>
              <div className="strategies-section-heading">
                <div>
                  <small>{t("Strategies")}</small>
                  <strong>{formatMarketPair(selected.market) || selected.market || "—"}</strong>
                </div>
              </div>

              <section ref={strategiesGridRef} className="strategies-grid" aria-label={t("All strategy results")}>
                {orderedStrategies.map((strategy) => {
                  const isDragging = draggedStrategyCode === strategy.strategy_code;
                  const visual = STRATEGY_VISUALS[strategy.strategy_code] || { accent: "#7182ff" };

                  if (isDragging) {
                    return (
                      <div
                        key={strategy.strategy_code}
                        className="strategy-card-placeholder"
                        data-strategy-placeholder={strategy.strategy_code}
                        data-strategy-key={strategy.strategy_code}
                        style={{
                          "--strategy-accent": visual.accent,
                          minHeight: draggedCardHeight ? `${draggedCardHeight}px` : undefined,
                        }}
                        aria-hidden="true"
                      />
                    );
                  }

                  return (
                    <StrategyCard
                      key={strategy.strategy_code}
                      strategy={strategy}
                      decision={decisionsByStrategy[strategy.strategy_code]}
                      experiment={selected}
                      language={language}
                      t={t}
                      dragging={false}
                      onPointerDown={startStrategyDrag}
                      onMove={moveStrategyByOffset}
                      onRetryHistory={openHistoryRetryDialog}
                      retryingHistory={retryingHistory}
                      onRetryResearch={openResearchRetryDialog}
                      retryingResearch={retryingResearch}
                    />
                  );
                })}
              </section>

              <footer className="dashboard-footer">
                <span>{t("Last frontend refresh")}: {lastFrontendRefresh ? formatTime(lastFrontendRefresh, language) : "—"} UTC</span>
                <span>{t("Paper trading only · No real orders")}</span>
              </footer>
            </>
          )}

          {loading && <div className="loading-indicator">{t("Refreshing…")}</div>}
        </section>
      </main>

      {isConfigurationOpen && (
        <SetupDialog
          configuration={configuration}
          form={form}
          setForm={setForm}
          hasRunningExperiment={experiments.some((item) => item.status === "RUNNING")}
          saving={saving}
          onSubmit={createExperiment}
          onSelectProfile={selectProfile}
          onStop={openStopDialog}
          onClose={closeConfiguration}
          language={language}
          t={t}
        />
      )}

      <StopDialog
        open={isStopOpen}
        adminKey={adminKey}
        setAdminKey={setAdminKey}
        closeOpenPositions={closeOpenPositions}
        setCloseOpenPositions={setCloseOpenPositions}
        error={stopError}
        stopping={stopping}
        onClose={closeStopDialog}
        onConfirm={confirmStop}
        t={t}
      />

      <HistoryRetryDialog
        open={isHistoryRetryOpen}
        adminKey={historyAdminKey}
        setAdminKey={setHistoryAdminKey}
        error={historyRetryError}
        retrying={retryingHistory}
        onClose={closeHistoryRetryDialog}
        onConfirm={confirmHistoryRetry}
        t={t}
      />

      <ResearchRetryDialog
        open={isResearchRetryOpen}
        adminKey={researchAdminKey}
        setAdminKey={setResearchAdminKey}
        error={researchRetryError}
        retrying={retryingResearch}
        onClose={closeResearchRetryDialog}
        onConfirm={confirmResearchRetry}
        t={t}
      />
    </div>
  );
}
