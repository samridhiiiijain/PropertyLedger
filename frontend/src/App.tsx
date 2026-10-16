import { FormEvent, useEffect, useMemo, useState } from "react";

import "./App.css";

// Response types for the FastAPI backend. Field names follow the backend models
// exactly, so API responses are used as they arrive, without mapping.
type InvoiceStatus = "UNPAID" | "PARTIALLY_PAID" | "PAID" | "ON_HOLD";
type ErrorKind = "invalid-filter" | "service";

interface PropertySummary {
  property_id: string;
  name: string;
  city: string;
  property_type: string;
  status: string;
}

interface ProjectSummary {
  project_id: string;
  name: string;
}

interface VendorSummary {
  vendor_id: string;
  name: string;
  category: string;
  city: string;
  tax_id: string;
}

interface PurchaseOrderSummary {
  po_id: string;
  committed_amount: string;
  currency: string;
}

interface PaymentSummary {
  payment_id: string;
  amount: string;
  payment_date: string;
}

interface BudgetSummary {
  budget_id: string | null;
  cost_code: string;
  approved_amount: string | null;
  currency: string;
}

interface InvoiceRecord {
  invoice_id: string;
  invoice_number: string;
  property: PropertySummary;
  project: ProjectSummary;
  vendor: VendorSummary;
  purchase_order: PurchaseOrderSummary;
  budget: BudgetSummary;
  payments: PaymentSummary[];
  invoice_date: string;
  due_date: string;
  amount: string;
  paid_amount: string;
  outstanding_amount: string;
  currency: string;
  status: InvoiceStatus;
}

interface InvoiceListResponse {
  items: InvoiceRecord[];
  count: number;
  filters: {
    project_id: string | null;
  };
}

// Structured Checks tab: unpaid invoices, invoice-vs-PO variances and budget
// variances for one project, each from its own /api/projects/{id}/... endpoint.
interface UnpaidInvoiceRecord {
  invoice_id: string;
  vendor_id: string;
  vendor_name: string;
  status: InvoiceStatus;
  invoice_amount: string;
  paid_amount: string;
  outstanding_amount: string;
  due_date: string;
}

interface PurchaseOrderVarianceRecord {
  invoice_id: string;
  po_id: string;
  vendor_name: string;
  invoice_amount: string;
  po_total: string;
  variance_amount: string;
  cost_code: string;
}

interface BudgetVarianceRecord {
  budget_id: string;
  cost_code: string;
  cost_category: string;
  budget_amount: string;
  committed_amount: string;
  variance_amount: string;
}

interface StructuredCheckResponse<T> {
  project_id: string;
  items: T[];
  count: number;
}

interface StructuredChecks {
  unpaidInvoices: StructuredCheckResponse<UnpaidInvoiceRecord>;
  poVariances: StructuredCheckResponse<PurchaseOrderVarianceRecord>;
  budgetVariances: StructuredCheckResponse<BudgetVarianceRecord>;
}

// Document Evidence tab (retrieved passages) and Connected Evidence tab
// (one invoice record plus the documents linked to it by stable IDs).
interface DocumentMetadata {
  document_id: string;
  document_type: string;
  document_date: string | null;
  source_file: string;
  property_id: string | null;
  project_id: string | null;
  vendor_id: string | null;
  invoice_id: string | null;
  po_id: string | null;
  cost_code: string | null;
}

interface DocumentEvidence {
  chunk_id: string;
  score: number;
  text: string;
  metadata: DocumentMetadata;
}

interface DocumentAnswerResponse {
  question: string;
  answer: string;
  status: "answered" | "no_evidence";
  confidence: number;
  latency_ms: number;
  sources: DocumentEvidence[];
}

interface LinkedInvoiceFacts {
  invoice_id: string;
  property_id: string;
  project_id: string;
  vendor_id: string;
  po_id: string;
  cost_code: string;
  status: InvoiceStatus;
  invoice_amount: string;
  po_amount: string;
  po_variance_amount: string;
  paid_amount: string;
  outstanding_amount: string;
  currency: string;
}

interface LinkedDocumentEvidence extends DocumentEvidence {
  link_type: string;
  matched_identifiers: string[];
}

interface LinkedInvoiceEvidenceResponse {
  invoice_id: string;
  status: "linked" | "missing_link";
  answer: string;
  structured_facts: LinkedInvoiceFacts;
  sources: LinkedDocumentEvidence[];
}

// Relationship Graph tab: PO variance paths traced in Neo4j, e.g.
// property -> project -> invoice -> PO -> vendor -> document.
interface RelationshipNode {
  label: string;
  id: string;
  display: string;
}

interface RelationshipEdge {
  type: string;
  from: string;
  to: string;
}

interface RelationshipPathRecord {
  finding: string;
  status: "supported" | "missing_evidence";
  invoice_id: string;
  property_id: string;
  project_id: string;
  po_id: string;
  vendor_id: string;
  cost_code: string;
  document_id: string | null;
  invoice_amount: string;
  po_amount: string;
  variance_amount: string;
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
}

interface RelationshipPathResponse {
  property_id: string;
  question: string;
  answer: string;
  count: number;
  paths: RelationshipPathRecord[];
}

// Approved finance terms (po-variance, unpaid-invoice, cost-code-over-budget).
interface BusinessDefinition {
  slug: string;
  term: string;
  definition: string;
  grain: string;
  calculation: string | null;
  applies_when: string;
  fields: string[];
  relationships: string[];
  used_by: string[];
  synonyms: string[];
  owner: string;
  version: string;
}

interface BusinessDefinitionListResponse {
  items: BusinessDefinition[];
  count: number;
}

// Source-selection plan from /api/evidence-selection. The workflow response
// carries the same plan so both tabs can show which sources were chosen.
type EvidenceSource =
  | "structured_store"
  | "document_index"
  | "linked_evidence"
  | "relationship_graph"
  | "business_definitions";

type SelectionStatus =
  | "answered"
  | "needs_clarification"
  | "unsupported"
  | "service_unavailable";

type QuestionIntent =
  | "structured_check"
  | "document_answer"
  | "relationship_path"
  | "linked_evidence"
  | "combined_evidence"
  | "ambiguous"
  | "unsupported";

interface DetectedEntity {
  entity_type: string;
  value: string;
}

interface ApprovedTermReference {
  slug: string;
  term: string;
  version: string;
}

interface EvidenceRequirement {
  need: string;
  source: EvidenceSource;
  reason: string;
  fields: string[];
}

interface EvidenceSelectionPlan {
  question: string;
  status: SelectionStatus;
  intent: QuestionIntent;
  entities: DetectedEntity[];
  approved_terms: ApprovedTermReference[];
  selected_sources: EvidenceSource[];
  evidence_requirements: EvidenceRequirement[];
  message: string;
  clarification_options: string[];
}

// /api/workflow-answer response: plan, validation result, evidence from the
// sources that actually ran, the final answer, and the step-by-step trace.
type WorkflowStatus =
  | "answered"
  | "needs_clarification"
  | "rejected"
  | "service_unavailable";

type WorkflowStepStatus = "pending" | "completed" | "skipped" | "failed";

interface WorkflowValidationResult {
  is_valid: boolean;
  message: string;
  missing_requirements: string[];
}

interface WorkflowEvidence {
  source: EvidenceSource;
  summary: string;
  references: string[];
}

interface WorkflowTraceStep {
  step: string;
  label: string;
  status: WorkflowStepStatus;
  message: string;
  selected_sources: EvidenceSource[];
}

interface WorkflowAnswerResponse {
  question: string;
  status: WorkflowStatus;
  intent: QuestionIntent;
  answer: string;
  plan: EvidenceSelectionPlan;
  validation: WorkflowValidationResult;
  evidence: WorkflowEvidence[];
  trace: WorkflowTraceStep[];
}

type CapabilityTab =
  | "workflow"
  | "structured"
  | "meaning"
  | "selection"
  | "documents"
  | "connected"
  | "relationships";

// Falls back to the local uvicorn server when VITE_API_BASE_URL isn't set.
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

// Project shortcut buttons under the filter. PR999 is there on purpose to show
// the empty-results state.
const QUICK_FILTERS = [
  { label: "All invoices", value: "" },
  { label: "PR204", value: "PR204" },
  { label: "PR205", value: "PR205" },
  { label: "PR206", value: "PR206" },
  { label: "Try PR999", value: "PR999" },
] as const;

// Sample prompts for the Document Evidence tab.
const DOCUMENT_QUESTIONS = [
  {
    label: "Procedure",
    question: "What does the finance procedure require before invoice approval?",
  },
  {
    label: "Missing evidence",
    question: "Which documents are missing before INV5003 can proceed?",
  },
  {
    label: "Wrong project",
    question: "Can DOC-UNRELATED-206 be used to answer a PR204 invoice question?",
  },
  {
    label: "No evidence",
    question: "Which invoice will definitely be paid tomorrow?",
  },
] as const;

// Sample prompts shared by the Workflow and Evidence Selection tabs, covering
// structured, document, graph, ambiguous and unsupported questions.
const SOURCE_SELECTION_QUESTIONS = [
  {
    label: "Exact records",
    question: "Which PR204 invoices are unpaid?",
  },
  {
    label: "Document policy",
    question: "What does the finance procedure require before invoice approval?",
  },
  {
    label: "Relationship path",
    question: "Trace PO variance paths for P204.",
  },
  {
    label: "Combined evidence",
    question: "Show the PO variance evidence for INV5004.",
  },
  {
    label: "Unsupported",
    question: "What is the vendor risk score for V301?",
  },
  {
    label: "Clarify",
    question: "Show me the variance for PR204.",
  },
] as const;

// Tab bar order and labels. Workflow is first because it's the default view.
const CAPABILITY_TABS: { id: CapabilityTab; label: string; description: string }[] = [
  {
    id: "workflow",
    label: "Workflow",
    description: "Validate + execute",
  },
  {
    id: "selection",
    label: "Evidence Selection",
    description: "Choose minimum sources",
  },
  {
    id: "structured",
    label: "Structured Checks",
    description: "Exact SQL answers",
  },
  {
    id: "meaning",
    label: "Business Meaning",
    description: "Approved definitions",
  },
  {
    id: "documents",
    label: "Document Evidence",
    description: "RAG source passages",
  },
  {
    id: "connected",
    label: "Connected Evidence",
    description: "Invoice-to-document IDs",
  },
  {
    id: "relationships",
    label: "Relationship Graph",
    description: "Neo4j path trace",
  },
];

// Amounts come from the API as strings (e.g. "485000.00") so they stay exact;
// they're only turned into numbers here for display.
function formatCurrency(value: string, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

// Dates are formatted in UTC so a YYYY-MM-DD value doesn't shift by a day in
// time zones behind UTC.
function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

// PARTIALLY_PAID -> "Partially Paid".
function displayStatus(status: InvoiceStatus): string {
  return status
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// Connected Evidence: turns a matched ID field name such as "po_id" into a
// readable label with the actual value, e.g. "PO PO7004".
function describeMatchedIdentifier(
  identifier: string,
  facts: LinkedInvoiceFacts,
): string {
  const labels: Record<string, string> = {
    property_id: `Property ${facts.property_id}`,
    project_id: `Project ${facts.project_id}`,
    vendor_id: `Vendor ${facts.vendor_id}`,
    invoice_id: `Invoice ${facts.invoice_id}`,
    po_id: `PO ${facts.po_id}`,
    cost_code: `Cost code ${facts.cost_code}`,
  };

  return labels[identifier] ?? identifier;
}

// Heading for a structured check, e.g. "PO variance - v0.6". Uses the fallback
// text until the definitions have loaded.
function definitionLabel(definition: BusinessDefinition | undefined, fallback: string): string {
  return definition ? `${definition.term} - ${definition.version}` : fallback;
}

// Backend source keys -> the tab names the user sees.
function displaySource(source: EvidenceSource): string {
  const labels: Record<EvidenceSource, string> = {
    business_definitions: "Business Meaning",
    structured_store: "Structured Records",
    document_index: "Document Evidence",
    linked_evidence: "Linked Evidence",
    relationship_graph: "Relationship Graph",
  };

  return labels[source];
}

function displayEntityType(entityType: string): string {
  return entityType
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function displayIntent(intent: QuestionIntent): string {
  return intent
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// One-sentence summary at the top of the Evidence Selection result, e.g.
// "This question needs Structured Records and Linked Evidence."
function selectionHeadline(plan: EvidenceSelectionPlan): string {
  if (plan.status === "unsupported") {
    return "This question cannot be answered safely from the approved sources yet.";
  }

  if (plan.status === "needs_clarification") {
    return "This question needs one more business choice before evidence is fetched.";
  }

  if (plan.selected_sources.length === 0) {
    return "No evidence source was selected for this question.";
  }

  const sources = plan.selected_sources.map(displaySource);
  if (sources.length === 1) {
    return `This question can be answered from ${sources[0]}.`;
  }

  const lastSource = sources[sources.length - 1];
  return `This question needs ${sources.slice(0, -1).join(", ")} and ${lastSource}.`;
}

// Tells the user which tab to open for the full answer once a plan is chosen.
function answerDestination(plan: EvidenceSelectionPlan): string {
  if (plan.status === "unsupported") {
    return "No answer route is available until this term is approved.";
  }

  if (plan.status === "needs_clarification") {
    return "Choose a specific approved meaning first, then run source selection again.";
  }

  const destinations: Record<QuestionIntent, string> = {
    structured_check: "Open Structured Checks for the exact SQL-backed answer.",
    document_answer: "Open Document Evidence for the grounded document answer and citation.",
    relationship_path: "Open Relationship Graph for the Neo4j path trace.",
    linked_evidence: "Open Connected Evidence for invoice-to-document support.",
    combined_evidence: "Open Connected Evidence for the linked evidence answer.",
    ambiguous: "Clarify the business meaning before answering.",
    unsupported: "No answer route is available for this question.",
  };

  return destinations[plan.intent];
}

function workflowStatusLabel(status: WorkflowStatus): string {
  const labels: Record<WorkflowStatus, string> = {
    answered: "Answered",
    needs_clarification: "Needs clarification",
    rejected: "Rejected",
    service_unavailable: "Service unavailable",
  };

  return labels[status];
}

function displayWorkflowStep(step: string): string {
  return step
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// Breaks a long workflow answer into lines for display. Short answers stay on
// one line. Otherwise it splits between sentences.
function workflowAnswerLines(answer: string): string[] {
  const normalized = answer.trim();
  if (normalized.length <= 180) {
    return [normalized];
  }

  return normalized
    .replace(/, (INV\d{4} links to)/g, ". $1")
    .replace(/\. (Based on )/g, ".\n$1")
    .replace(/\. (Document sources reviewed:)/g, ".\n$1")
    .split(/\n|(?<=\.)(?<!(?:^|\s)\d{1,2}\.)\s+(?=[A-Z])|\s+(?=\d{1,2}\.\s)|\s+(?=- [A-Z])/)
    .map((line) => line.trim())
    .filter(Boolean);
}

// Shown while the invoice list is loading.
function LoadingState() {
  return (
    <section className="state-panel loading-panel" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <div>
        <h2>Loading invoice records</h2>
        <p>Connecting to the Day 2 structured finance API.</p>
      </div>
    </section>
  );
}

// API calls. Each one wraps a single backend endpoint and turns a 422 or
// error status into an Error with a message the UI can show.

// A 422 here means the project ID failed validation. The invoice loader
// catches INVALID_PROJECT_ID and shows the filter hint instead of a service error.
async function fetchStructuredCheck<T>(
  path: string,
  signal: AbortSignal,
): Promise<StructuredCheckResponse<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (response.status === 422) {
    throw new Error("INVALID_PROJECT_ID");
  }

  if (!response.ok) {
    throw new Error(`The service returned status ${response.status}.`);
  }

  return (await response.json()) as StructuredCheckResponse<T>;
}

// project_id is only sent when a project filter is active, so answers stay
// inside that project's documents.
async function fetchDocumentAnswer(
  question: string,
  projectId: string,
): Promise<DocumentAnswerResponse> {
  const params = new URLSearchParams({ question });
  if (projectId) {
    params.set("project_id", projectId);
  }

  const response = await fetch(`${API_BASE_URL}/api/document-answer?${params}`, {
    headers: { Accept: "application/json" },
  });

  if (response.status === 422) {
    throw new Error("Use a clear question and a valid project ID such as PR204.");
  }

  if (!response.ok) {
    throw new Error(`The document service returned status ${response.status}.`);
  }

  return (await response.json()) as DocumentAnswerResponse;
}

async function fetchLinkedInvoiceEvidence(
  invoiceId: string,
): Promise<LinkedInvoiceEvidenceResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/invoices/${encodeURIComponent(invoiceId)}/linked-evidence`,
    { headers: { Accept: "application/json" } },
  );

  if (response.status === 422) {
    throw new Error("Use an invoice ID in the format INV followed by four digits, for example INV5004.");
  }

  if (response.status === 404) {
    const payload = (await response.json()) as { detail?: string };
    throw new Error(payload.detail ?? "No structured invoice record was found.");
  }

  if (!response.ok) {
    throw new Error(`The linked evidence service returned status ${response.status}.`);
  }

  return (await response.json()) as LinkedInvoiceEvidenceResponse;
}

async function fetchRelationshipPaths(
  propertyId: string,
): Promise<RelationshipPathResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/properties/${encodeURIComponent(propertyId)}/po-variance-paths`,
    { headers: { Accept: "application/json" } },
  );

  if (response.status === 422) {
    throw new Error("Use a property ID in the format P followed by three digits, for example P204.");
  }

  if (response.status === 503) {
    const payload = (await response.json()) as { detail?: string };
    throw new Error(payload.detail ?? "Neo4j relationship graph is unavailable.");
  }

  if (!response.ok) {
    throw new Error(`The relationship graph service returned status ${response.status}.`);
  }

  return (await response.json()) as RelationshipPathResponse;
}

async function fetchBusinessDefinitions(
  signal: AbortSignal,
): Promise<BusinessDefinitionListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/business-definitions`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`The business definition service returned status ${response.status}.`);
  }

  return (await response.json()) as BusinessDefinitionListResponse;
}

async function fetchEvidenceSelectionPlan(
  question: string,
): Promise<EvidenceSelectionPlan> {
  const params = new URLSearchParams({ question });
  const response = await fetch(`${API_BASE_URL}/api/evidence-selection?${params}`, {
    headers: { Accept: "application/json" },
  });

  if (response.status === 422) {
    throw new Error("Use a clear question between 8 and 300 characters.");
  }

  if (!response.ok) {
    throw new Error(`The evidence selection service returned status ${response.status}.`);
  }

  return (await response.json()) as EvidenceSelectionPlan;
}

// Runs the full workflow: plan, validate, execute the selected sources, answer.
async function fetchWorkflowAnswer(
  question: string,
): Promise<WorkflowAnswerResponse> {
  const params = new URLSearchParams({ question });
  const response = await fetch(`${API_BASE_URL}/api/workflow-answer?${params}`, {
    headers: { Accept: "application/json" },
  });

  if (response.status === 422) {
    throw new Error("Use a clear question between 8 and 300 characters.");
  }

  if (response.status === 503) {
    const payload = (await response.json()) as { detail?: string };
    throw new Error(payload.detail ?? "The workflow service is unavailable.");
  }

  if (!response.ok) {
    throw new Error(`The workflow service returned status ${response.status}.`);
  }

  return (await response.json()) as WorkflowAnswerResponse;
}

interface AppError {
  kind: ErrorKind;
  message: string;
}

// The whole single-page UI: filter, summary cards, tab bar, and every tab's
// panel. Each tab keeps its own input, result, loading flag and error in state
// below, so switching tabs doesn't clear what was already fetched.
function App() {
  // Shared state: active tab, project filter and invoice data.
  const [activeTab, setActiveTab] = useState<CapabilityTab>("workflow");
  const [projectInput, setProjectInput] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [data, setData] = useState<InvoiceListResponse | null>(null);
  const [checks, setChecks] = useState<StructuredChecks | null>(null);
  // Per-tab state: question/input, response, loading flag, error message.
  const [documentQuestion, setDocumentQuestion] = useState<string>(DOCUMENT_QUESTIONS[0].question);
  const [documentAnswer, setDocumentAnswer] = useState<DocumentAnswerResponse | null>(null);
  const [isDocumentLoading, setIsDocumentLoading] = useState(false);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [linkedInvoiceInput, setLinkedInvoiceInput] = useState("INV5004");
  const [linkedEvidence, setLinkedEvidence] = useState<LinkedInvoiceEvidenceResponse | null>(null);
  const [isLinkedEvidenceLoading, setIsLinkedEvidenceLoading] = useState(false);
  const [linkedEvidenceError, setLinkedEvidenceError] = useState<string | null>(null);
  const [relationshipPropertyInput, setRelationshipPropertyInput] = useState("P204");
  const [relationshipPaths, setRelationshipPaths] = useState<RelationshipPathResponse | null>(null);
  const [isRelationshipLoading, setIsRelationshipLoading] = useState(false);
  const [relationshipError, setRelationshipError] = useState<string | null>(null);
  const [businessDefinitions, setBusinessDefinitions] = useState<BusinessDefinition[]>([]);
  const [isBusinessDefinitionLoading, setIsBusinessDefinitionLoading] = useState(true);
  const [businessDefinitionError, setBusinessDefinitionError] = useState<string | null>(null);
  const [selectionQuestion, setSelectionQuestion] = useState<string>(SOURCE_SELECTION_QUESTIONS[0].question);
  const [selectionPlan, setSelectionPlan] = useState<EvidenceSelectionPlan | null>(null);
  const [isSelectionLoading, setIsSelectionLoading] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [workflowQuestion, setWorkflowQuestion] = useState<string>(SOURCE_SELECTION_QUESTIONS[0].question);
  const [workflowAnswer, setWorkflowAnswer] = useState<WorkflowAnswerResponse | null>(null);
  const [isWorkflowLoading, setIsWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<AppError | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    // Loads the invoice register. When a project is filtered it also loads that
    // project's three structured checks at the same time. Runs again whenever the
    // filter changes or refreshKey is bumped; the AbortController drops a
    // response from a previous filter that arrives late.
    async function loadInvoices() {
      setIsLoading(true);
      setError(null);

      const query = projectFilter
        ? `?project_id=${encodeURIComponent(projectFilter)}`
        : "";

      try {
        const response = await fetch(`${API_BASE_URL}/api/invoices${query}`, {
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });

        if (response.status === 422) {
          throw new Error("INVALID_PROJECT_ID");
        }

        if (!response.ok) {
          throw new Error(`The service returned status ${response.status}.`);
        }

        const payload = (await response.json()) as InvoiceListResponse;
        setData(payload);
        if (projectFilter) {
          const [
            unpaidInvoices,
            poVariances,
            budgetVariances,
          ] = await Promise.all([
            fetchStructuredCheck<UnpaidInvoiceRecord>(
              `/api/projects/${projectFilter}/unpaid-invoices`,
              controller.signal,
            ),
            fetchStructuredCheck<PurchaseOrderVarianceRecord>(
              `/api/projects/${projectFilter}/po-variances`,
              controller.signal,
            ),
            fetchStructuredCheck<BudgetVarianceRecord>(
              `/api/projects/${projectFilter}/budget-variances`,
              controller.signal,
            ),
          ]);

          setChecks({ unpaidInvoices, poVariances, budgetVariances });
        } else {
          setChecks(null);
        }
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }

        setData(null);
        if (
          requestError instanceof Error &&
          requestError.message === "INVALID_PROJECT_ID"
        ) {
          setError({
            kind: "invalid-filter",
            message: "Use a project ID in the format PR followed by three digits, for example PR204.",
          });
          return;
        }

        setError({
          kind: "service",
          message:
            requestError instanceof Error
              ? requestError.message
              : "The invoice service could not be reached.",
        });
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }

    void loadInvoices();
    return () => controller.abort();
  }, [projectFilter, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();

    // Loaded once on start. The Structured Checks and Business Meaning tabs both
    // read the approved definitions from here.
    async function loadBusinessDefinitions() {
      setIsBusinessDefinitionLoading(true);
      setBusinessDefinitionError(null);

      try {
        const response = await fetchBusinessDefinitions(controller.signal);
        setBusinessDefinitions(response.items);
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }

        setBusinessDefinitions([]);
        setBusinessDefinitionError(
          requestError instanceof Error
            ? requestError.message
            : "The approved business definitions could not be loaded.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setIsBusinessDefinitionLoading(false);
        }
      }
    }

    void loadBusinessDefinitions();
    return () => controller.abort();
  }, []);

  // Numbers for the summary cards above the tabs.
  const propertyCount = useMemo(
    () => new Set(data?.items.map((invoice) => invoice.property.property_id)).size,
    [data],
  );

  const openInvoiceCount = useMemo(
    () => data?.items.filter((invoice) => invoice.status !== "PAID").length ?? 0,
    [data],
  );

  // Picks each approved definition out of the loaded list so the structured
  // checks can show the rule and version they were calculated with.
  const poVarianceDefinition = useMemo(
    () => businessDefinitions.find((definition) => definition.slug === "po-variance"),
    [businessDefinitions],
  );

  const unpaidInvoiceDefinition = useMemo(
    () => businessDefinitions.find((definition) => definition.slug === "unpaid-invoice"),
    [businessDefinitions],
  );

  const costCodeOverBudgetDefinition = useMemo(
    () => businessDefinitions.find((definition) => definition.slug === "cost-code-over-budget"),
    [businessDefinitions],
  );

  function showBusinessMeaning() {
    setActiveTab("meaning");
  }

  // Project filter handlers. Picking the project that is already active bumps
  // refreshKey so the data is fetched again instead of nothing happening.
  function applyFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = projectInput.trim().toUpperCase();
    setProjectInput(normalized);

    if (normalized === projectFilter) {
      setRefreshKey((current) => current + 1);
    } else {
      setProjectFilter(normalized);
    }
  }

  function clearFilter() {
    setProjectInput("");
    if (projectFilter === "") {
      setRefreshKey((current) => current + 1);
    } else {
      setProjectFilter("");
    }
  }

  function selectQuickFilter(value: string) {
    setProjectInput(value);
    if (value === projectFilter) {
      setRefreshKey((current) => current + 1);
    } else {
      setProjectFilter(value);
    }
  }

  // Document Evidence tab: ask a question against the document index, scoped to
  // the current project filter.
  async function askDocumentQuestion(question: string = documentQuestion) {
    const normalized = question.trim();
    if (!normalized) {
      setDocumentError("Enter a document question first.");
      return;
    }

    setDocumentQuestion(normalized);
    setIsDocumentLoading(true);
    setDocumentError(null);

    try {
      const response = await fetchDocumentAnswer(normalized, projectFilter);
      setDocumentAnswer(response);
    } catch (requestError) {
      setDocumentAnswer(null);
      setDocumentError(
        requestError instanceof Error
          ? requestError.message
          : "The document evidence service could not be reached.",
      );
    } finally {
      setIsDocumentLoading(false);
    }
  }

  function submitDocumentQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void askDocumentQuestion();
  }

  function selectDocumentQuestion(question: string) {
    void askDocumentQuestion(question);
  }

  function clearDocumentQuestion() {
    setDocumentQuestion("");
    setDocumentAnswer(null);
    setDocumentError(null);
  }

  // Evidence Selection tab: shows which sources a question would use, without
  // running any of them.
  async function planEvidenceSelection(question: string = selectionQuestion) {
    const normalized = question.trim();
    if (!normalized) {
      setSelectionError("Enter a business question first.");
      return;
    }

    setSelectionQuestion(normalized);
    setIsSelectionLoading(true);
    setSelectionError(null);

    try {
      const response = await fetchEvidenceSelectionPlan(normalized);
      setSelectionPlan(response);
    } catch (requestError) {
      setSelectionPlan(null);
      setSelectionError(
        requestError instanceof Error
          ? requestError.message
          : "The evidence selection service could not be reached.",
      );
    } finally {
      setIsSelectionLoading(false);
    }
  }

  function submitEvidenceSelection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void planEvidenceSelection();
  }

  function selectEvidenceQuestion(question: string) {
    void planEvidenceSelection(question);
  }

  function clearEvidenceSelection() {
    setSelectionQuestion("");
    setSelectionPlan(null);
    setSelectionError(null);
    setIsSelectionLoading(false);
  }

  // Workflow tab: runs the question end to end and stores the plan, validation,
  // evidence, answer and trace together.
  async function runWorkflow(question: string = workflowQuestion) {
    const normalized = question.trim();
    if (!normalized) {
      setWorkflowError("Enter a business question first.");
      return;
    }

    setWorkflowQuestion(normalized);
    setIsWorkflowLoading(true);
    setWorkflowError(null);

    try {
      const response = await fetchWorkflowAnswer(normalized);
      setWorkflowAnswer(response);
    } catch (requestError) {
      setWorkflowAnswer(null);
      setWorkflowError(
        requestError instanceof Error
          ? requestError.message
          : "The workflow service could not be reached.",
      );
    } finally {
      setIsWorkflowLoading(false);
    }
  }

  function submitWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runWorkflow();
  }

  function selectWorkflowQuestion(question: string) {
    void runWorkflow(question);
  }

  function clearWorkflow() {
    setWorkflowQuestion("");
    setWorkflowAnswer(null);
    setWorkflowError(null);
    setIsWorkflowLoading(false);
  }

  // Connected Evidence tab: one invoice's structured facts plus the documents
  // linked to it by invoice, PO, vendor, cost code, project or property ID.
  async function loadLinkedInvoiceEvidence(invoiceId: string = linkedInvoiceInput) {
    const normalized = invoiceId.trim().toUpperCase();
    if (!normalized) {
      setLinkedEvidenceError("Enter an invoice ID first.");
      return;
    }

    setLinkedInvoiceInput(normalized);
    setIsLinkedEvidenceLoading(true);
    setLinkedEvidenceError(null);

    try {
      const response = await fetchLinkedInvoiceEvidence(normalized);
      setLinkedEvidence(response);
    } catch (requestError) {
      setLinkedEvidence(null);
      setLinkedEvidenceError(
        requestError instanceof Error
          ? requestError.message
          : "The linked evidence service could not be reached.",
      );
    } finally {
      setIsLinkedEvidenceLoading(false);
    }
  }

  function submitLinkedInvoiceEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadLinkedInvoiceEvidence();
  }

  function clearLinkedInvoiceEvidence() {
    setLinkedInvoiceInput("");
    setLinkedEvidence(null);
    setLinkedEvidenceError(null);
    setIsLinkedEvidenceLoading(false);
  }

  // Relationship Graph tab: PO variance paths for a property, traced in Neo4j.
  async function loadRelationshipPaths(propertyId: string = relationshipPropertyInput) {
    const normalized = propertyId.trim().toUpperCase();
    if (!normalized) {
      setRelationshipError("Enter a property ID first.");
      return;
    }

    setRelationshipPropertyInput(normalized);
    setIsRelationshipLoading(true);
    setRelationshipError(null);

    try {
      const response = await fetchRelationshipPaths(normalized);
      setRelationshipPaths(response);
    } catch (requestError) {
      setRelationshipPaths(null);
      setRelationshipError(
        requestError instanceof Error
          ? requestError.message
          : "The Neo4j relationship graph service could not be reached.",
      );
    } finally {
      setIsRelationshipLoading(false);
    }
  }

  function submitRelationshipPaths(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadRelationshipPaths();
  }

  function clearRelationshipPaths() {
    setRelationshipPropertyInput("");
    setRelationshipPaths(null);
    setRelationshipError(null);
    setIsRelationshipLoading(false);
  }

  return (
    <div className="app-shell">
      {/* App name and version badge */}
      <header className="topbar">
        <a className="brand" href="#main-content" aria-label="Go to invoice overview">
          <span className="brand-mark" aria-hidden="true">PL</span>
          <span>
            <strong>PropertyLedger</strong>
            <small>Real Estate Finance Process Automation Assistant</small>
          </span>
        </a>
        <span className="version-badge">Day 9 - v1.0</span>
      </header>

      <main id="main-content">
        <section className="hero">
          <div>
            <p className="eyebrow">Invoice workspace</p>
            <h1>Finance records, clearly connected.</h1>
            <p className="hero-copy">
              Review structured invoice records with their property, project, vendor,
              purchase order, payment, budget, cost-code identifiers, linked evidence, and relationship paths.
            </p>
          </div>
          <div className="source-note">
            <span className="source-dot" aria-hidden="true" />
            <div>
              <strong>Data and evidence</strong>
              <span>SQLite records + Neo4j relationship paths</span>
            </div>
          </div>
        </section>

        {/* Project filter. Applies to the invoice register, structured checks and document questions. */}
        <section className="filter-card" aria-labelledby="filter-heading">
          <div>
            <p className="section-label">Record filter</p>
            <h2 id="filter-heading">Find invoices by project</h2>
            <p>Choose a project such as PR204 or enter a project ID manually.</p>
            <div className="quick-filters" aria-label="Quick project filters">
              {QUICK_FILTERS.map((filter) => (
                <button
                  className={
                    projectFilter === filter.value
                      ? "quick-filter active"
                      : "quick-filter"
                  }
                  key={filter.label}
                  type="button"
                  onClick={() => selectQuickFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
          <form onSubmit={applyFilter} className="filter-form" noValidate>
            <label htmlFor="project-id">Project ID</label>
            <div className="filter-actions">
              <input
                id="project-id"
                name="project_id"
                value={projectInput}
                onChange={(event) => setProjectInput(event.target.value)}
                placeholder="PR204"
                maxLength={5}
                autoComplete="off"
              />
              <button className="primary-button" type="submit">Apply</button>
              <button className="secondary-button" type="button" onClick={clearFilter}>
                Clear
              </button>
            </div>
          </form>
        </section>

        {/* Loading, error and empty states for the invoice load. The tabs only render once invoices have loaded. */}
        {isLoading && <LoadingState />}

        {!isLoading && error && (
          <section className="state-panel error-panel" role="alert">
            <span className="state-icon" aria-hidden="true">!</span>
            <div>
              <h2>
                {error.kind === "invalid-filter"
                  ? "Project ID format is invalid"
                  : "Invoice data is unavailable"}
              </h2>
              <p>
                {error.message}
                {error.kind === "service"
                  ? " Confirm the backend is running, then try again."
                  : ""}
              </p>
              <button
                className="primary-button compact"
                type="button"
                onClick={() => setRefreshKey((current) => current + 1)}
              >
                Retry
              </button>
            </div>
          </section>
        )}

        {!isLoading && !error && data?.items.length === 0 && (
          <section className="state-panel empty-panel" aria-live="polite">
            <span className="state-icon" aria-hidden="true">0</span>
            <div>
              <h2>No invoices found</h2>
              <p>No invoices found for this project. Try All invoices or PR204.</p>
              <button className="secondary-button compact" type="button" onClick={clearFilter}>
                Show all invoices
              </button>
            </div>
          </section>
        )}

        {!isLoading && !error && data && data.items.length > 0 && (
          <section className="results" aria-live="polite">
            {/* Summary cards: invoice count, properties, open invoices */}
            <div className="summary-grid">
              <article className="summary-card">
                <span>Matching invoices</span>
                <strong>{data.count}</strong>
                <small>{projectFilter ? `Filtered to ${projectFilter}` : "All projects"}</small>
              </article>
              <article className="summary-card">
                <span>Properties represented</span>
                <strong>{propertyCount}</strong>
                <small>Linked by property_id</small>
              </article>
              <article className="summary-card accent-card">
                <span>Open invoices</span>
                <strong>{openInvoiceCount}</strong>
                <small>Unpaid or partially paid</small>
              </article>
            </div>

            {/* Tab bar. Only the active tab's panel is rendered below. */}
            <nav className="capability-tabs" aria-label="Workspace capabilities">
              {CAPABILITY_TABS.map((tab) => (
                <button
                  className={activeTab === tab.id ? "capability-tab active" : "capability-tab"}
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={activeTab === tab.id ? "page" : undefined}
                >
                  <span>{tab.label}</span>
                  <small>{tab.description}</small>
                </button>
              ))}
            </nav>

            {/* Structured Checks: SQL-backed unpaid, PO variance and budget variance tables (needs a project filter) */}
            {activeTab === "structured" && checks && (
              <section className="structured-checks" aria-labelledby="checks-heading">
                <div className="table-heading inline-heading">
                  <div>
                    <p className="section-label">Structured checks</p>
                    <h2 id="checks-heading">Exact checks for {checks.unpaidInvoices.project_id}</h2>
                  </div>
                  <span>SQL-backed calculations</span>
                </div>

                <div className="check-grid">
                  <article className="check-card">
                    <div className="check-card-title">
                      <h3>Unpaid invoices</h3>
                      <button className="definition-chip" type="button" onClick={showBusinessMeaning}>
                        {definitionLabel(unpaidInvoiceDefinition, "Unpaid invoice - v0.6")}
                      </button>
                    </div>
                    <strong>{checks.unpaidInvoices.count}</strong>
                    <ul>
                      {checks.unpaidInvoices.items.map((invoice) => (
                        <li key={invoice.invoice_id}>
                          <span>{invoice.invoice_id}</span>
                          <small>{invoice.vendor_name} - {displayStatus(invoice.status)}</small>
                        </li>
                      ))}
                    </ul>
                    {checks.unpaidInvoices.count === 0 && <p>No unpaid invoices found.</p>}
                  </article>

                  <article className="check-card">
                    <div className="check-card-title">
                      <h3>Invoices over PO</h3>
                      <button className="definition-chip" type="button" onClick={showBusinessMeaning}>
                        {definitionLabel(poVarianceDefinition, "PO variance - v0.6")}
                      </button>
                    </div>
                    <strong>{checks.poVariances.count}</strong>
                    <ul>
                      {checks.poVariances.items.map((variance) => (
                        <li key={variance.invoice_id}>
                          <span>{variance.invoice_id}</span>
                          <small>
                            {formatCurrency(variance.variance_amount, "INR")} over {variance.po_id}
                          </small>
                        </li>
                      ))}
                    </ul>
                    {checks.poVariances.count === 0 && <p>No PO variances found.</p>}
                  </article>

                  <article className="check-card">
                    <div className="check-card-title">
                      <h3>Cost codes above budget</h3>
                      <button className="definition-chip" type="button" onClick={showBusinessMeaning}>
                        {definitionLabel(costCodeOverBudgetDefinition, "Cost code over budget - v0.6")}
                      </button>
                    </div>
                    <strong>{checks.budgetVariances.count}</strong>
                    <ul>
                      {checks.budgetVariances.items.map((variance) => (
                        <li key={variance.cost_code}>
                          <span>{variance.cost_code}</span>
                          <small>
                            {variance.cost_category} - {formatCurrency(variance.variance_amount, "INR")} over
                          </small>
                        </li>
                      ))}
                    </ul>
                    {checks.budgetVariances.count === 0 && <p>No budget variances found.</p>}
                  </article>
                </div>
              </section>
            )}

            {/* Business Meaning: the approved definitions with grain, rule, calculation and version */}
            {activeTab === "meaning" && (
              <section className="business-meaning" aria-labelledby="meaning-heading">
                <div className="table-heading inline-heading">
                  <div>
                    <p className="section-label">Business meaning</p>
                    <h2 id="meaning-heading">Approved finance definitions</h2>
                  </div>
                  <span>Semantic layer v0.6</span>
                </div>

                <div className="meaning-body">
                  <p className="meaning-intro">
                    These terms are defined once and reused by the structured SQL checks and
                    Neo4j relationship traversal, so calculations keep the same meaning across the app.
                  </p>

                  {isBusinessDefinitionLoading && (
                    <div className="mini-state" aria-live="polite">
                      <span className="spinner small-spinner" aria-hidden="true" />
                      Loading approved definitions...
                    </div>
                  )}

                  {businessDefinitionError && (
                    <div className="mini-state error-text" role="alert">
                      {businessDefinitionError}
                    </div>
                  )}

                  {!isBusinessDefinitionLoading && !businessDefinitionError && (
                    <div className="definition-grid">
                      {businessDefinitions.map((definition) => (
                        <article className="definition-card" key={definition.slug}>
                          <div className="definition-heading">
                            <div>
                              <span className="definition-slug">{definition.slug}</span>
                              <h3>{definition.term}</h3>
                            </div>
                            <span>{definition.version}</span>
                          </div>

                          <p>{definition.definition}</p>

                          <dl className="definition-facts">
                            <div>
                              <dt>Grain</dt>
                              <dd>{definition.grain}</dd>
                            </div>
                            <div>
                              <dt>Rule</dt>
                              <dd>{definition.applies_when}</dd>
                            </div>
                            {definition.calculation && (
                              <div>
                                <dt>Calculation</dt>
                                <dd>{definition.calculation}</dd>
                              </div>
                            )}
                          </dl>

                          <div className="definition-section">
                            <strong>Fields</strong>
                            <div className="definition-tags">
                              {definition.fields.map((field) => (
                                <code key={field}>{field}</code>
                              ))}
                            </div>
                          </div>

                          <div className="definition-section">
                            <strong>Used by</strong>
                            <ul>
                              {definition.used_by.map((consumer) => (
                                <li key={consumer}>{consumer}</li>
                              ))}
                            </ul>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Workflow: question in; plan, validation, executed evidence, answer and trace out */}
            {activeTab === "workflow" && (
            <section className="workflow-panel" aria-labelledby="workflow-heading">
              <div className="table-heading inline-heading">
                <div>
                  <p className="section-label">Workflow orchestration</p>
                  <h2 id="workflow-heading">Run the validated evidence workflow</h2>
                  <p className="heading-support">
                    The workflow turns a business question into a validated source plan, runs only
                    the approved evidence path, and returns a traceable answer.
                  </p>
                </div>
                <span>Day 8 v0.8</span>
              </div>

              <div className="selection-body">
                <form className="selection-form" onSubmit={submitWorkflow}>
                  <label htmlFor="workflow-question">Business question</label>
                  <div className="selection-actions">
                    <input
                      id="workflow-question"
                      name="workflow-question"
                      value={workflowQuestion}
                      onChange={(event) => setWorkflowQuestion(event.target.value)}
                      placeholder="Ask a question and run the workflow"
                      autoComplete="off"
                    />
                    <button className="primary-button" type="submit">
                      Run workflow
                    </button>
                    <button className="secondary-button" type="button" onClick={clearWorkflow}>
                      Clear
                    </button>
                  </div>
                </form>

                <div className="selection-prompts" aria-label="Sample workflow questions">
                  {SOURCE_SELECTION_QUESTIONS.map((prompt) => (
                    <button
                      className="selection-prompt"
                      key={prompt.question}
                      type="button"
                      onClick={() => selectWorkflowQuestion(prompt.question)}
                    >
                      <span>{prompt.label}</span>
                      {prompt.question}
                    </button>
                  ))}
                </div>

                {isWorkflowLoading && (
                  <div className="mini-state" aria-live="polite">
                    <span className="spinner small-spinner" aria-hidden="true" />
                    Running the validated workflow...
                  </div>
                )}

                {workflowError && (
                  <div className="mini-state error-text" role="alert">
                    {workflowError}
                  </div>
                )}

                {workflowAnswer && !isWorkflowLoading && (
                  <div className="workflow-result">
                    <div className="selection-result-heading">
                      <div>
                        <span className={`answer-status ${workflowAnswer.status === "answered" ? "answered" : "no_evidence"}`}>
                          {workflowStatusLabel(workflowAnswer.status)}
                        </span>
                        <div className="workflow-answer-summary">
                          {workflowAnswerLines(workflowAnswer.answer).map((line) => (
                            <p key={line}>{line}</p>
                          ))}
                        </div>
                      </div>
                      <small>{displayIntent(workflowAnswer.intent)}</small>
                    </div>

                    <div className="workflow-stage-grid">
                      <article className="workflow-stage-card">
                        <span>Source-selection plan</span>
                        <strong>{selectionHeadline(workflowAnswer.plan)}</strong>
                        <p>{workflowAnswer.plan.message}</p>
                        {workflowAnswer.plan.selected_sources.length > 0 ? (
                          <div className="source-route compact-route" aria-label="Workflow selected route">
                            <div>
                              {workflowAnswer.plan.selected_sources.map((source, index) => (
                                <span className="source-route-step" key={source}>
                                  <span className={`source-node source-${source}`}>
                                    <small>Step {index + 1}</small>
                                    {displaySource(source)}
                                  </span>
                                  {index < workflowAnswer.plan.selected_sources.length - 1 && (
                                    <span className="source-route-arrow" aria-hidden="true">→</span>
                                  )}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <p className="no-source-note">
                            No source was executed because the plan requires clarification or is unsupported.
                          </p>
                        )}
                      </article>

                      <article className={`workflow-stage-card ${workflowAnswer.validation.is_valid ? "valid-card" : "invalid-card"}`}>
                        <div className="workflow-card-heading">
                          <span>Validation</span>
                          <em className={workflowAnswer.validation.is_valid ? "validation-badge passed" : "validation-badge failed"}>
                            {workflowAnswer.validation.is_valid ? "Validated ✓" : "Validation failed"}
                          </em>
                        </div>
                        <strong>
                          {workflowAnswer.validation.is_valid
                            ? "Plan validated before execution"
                            : "Plan rejected before execution"}
                        </strong>
                        <p>{workflowAnswer.validation.message}</p>
                        {workflowAnswer.validation.missing_requirements.length > 0 && (
                          <div className="definition-tags">
                            {workflowAnswer.validation.missing_requirements.map((requirement) => (
                              <code key={requirement}>{requirement}</code>
                            ))}
                          </div>
                        )}
                      </article>
                    </div>

                    {workflowAnswer.evidence.length > 0 && (
                      <div className="workflow-evidence-list">
                        {workflowAnswer.evidence.map((item) => (
                          <article className="requirement-card" key={`${item.source}-${item.summary}`}>
                            <span>{displaySource(item.source)}</span>
                            <strong>{item.summary}</strong>
                            {item.references.length > 0 && (
                              <div className="definition-tags">
                                {item.references.map((reference) => (
                                  <code key={`${item.source}-${reference}`}>{reference}</code>
                                ))}
                              </div>
                            )}
                          </article>
                        ))}
                      </div>
                    )}

                    <div className="workflow-trace">
                      <span>Workflow trace</span>
                      <div>
                        {workflowAnswer.trace.map((step, index) => (
                          <article className={`workflow-trace-step ${step.status}`} key={`${step.step}-${index}`}>
                            <small>Step {index + 1}</small>
                            <strong>{step.label || displayWorkflowStep(step.step)}</strong>
                            <p>{step.message}</p>
                            <em>{step.status}</em>
                          </article>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </section>
            )}

            {/* Evidence Selection: the source plan on its own, nothing is executed */}
            {activeTab === "selection" && (
            <section className="evidence-selection" aria-labelledby="selection-heading">
              <div className="table-heading inline-heading">
                <div>
                  <p className="section-label">Evidence selection</p>
                  <h2 id="selection-heading">Choose the minimum sufficient source</h2>
                  <p className="heading-support">
                    The app analyzes the question, identifies entities and approved terms, then selects
                    the source set needed before any evidence is fetched. This tab shows the evidence
                    plan, not the final business answer.
                  </p>
                </div>
                <span>Day 7 v0.7</span>
              </div>

              <div className="selection-body">
                <form className="selection-form" onSubmit={submitEvidenceSelection}>
                  <label htmlFor="selection-question">Business question</label>
                  <div className="selection-actions">
                    <input
                      id="selection-question"
                      name="selection-question"
                      value={selectionQuestion}
                      onChange={(event) => setSelectionQuestion(event.target.value)}
                      placeholder="Ask which source this question needs"
                      autoComplete="off"
                    />
                    <button className="primary-button" type="submit">
                      Plan evidence
                    </button>
                    <button className="secondary-button" type="button" onClick={clearEvidenceSelection}>
                      Clear
                    </button>
                  </div>
                </form>

                <div className="selection-prompts" aria-label="Sample source-selection questions">
                  {SOURCE_SELECTION_QUESTIONS.map((prompt) => (
                    <button
                      className="selection-prompt"
                      key={prompt.question}
                      type="button"
                      onClick={() => selectEvidenceQuestion(prompt.question)}
                    >
                      <span>{prompt.label}</span>
                      {prompt.question}
                    </button>
                  ))}
                </div>

                {isSelectionLoading && (
                  <div className="mini-state" aria-live="polite">
                    <span className="spinner small-spinner" aria-hidden="true" />
                    Planning required evidence sources...
                  </div>
                )}

                {selectionError && (
                  <div className="mini-state error-text" role="alert">
                    {selectionError}
                  </div>
                )}

                {selectionPlan && !isSelectionLoading && (
                  <div className="selection-result">
                    <div className="selection-result-heading">
                      <div>
                        <span className={`answer-status ${selectionPlan.status === "answered" ? "answered" : "no_evidence"}`}>
                          {selectionPlan.status === "answered"
                            ? "Plan ready"
                            : selectionPlan.status === "needs_clarification"
                              ? "Needs clarification"
                              : "Unsupported"}
                        </span>
                        <h3>{selectionHeadline(selectionPlan)}</h3>
                        <p>{selectionPlan.message}</p>
                      </div>
                      <small>{displayIntent(selectionPlan.intent)}</small>
                    </div>

                    <div className="answer-route-note">
                      <span>Where the answer lives</span>
                      <strong>{answerDestination(selectionPlan)}</strong>
                    </div>

                    {selectionPlan.selected_sources.length > 0 ? (
                      <div className="source-route" aria-label="Selected evidence route">
                        <span>Selected route</span>
                        <div>
                          {selectionPlan.selected_sources.map((source, index) => (
                            <span className="source-route-step" key={source}>
                              <span className={`source-node source-${source}`}>
                                <small>Step {index + 1}</small>
                                {displaySource(source)}
                              </span>
                              {index < selectionPlan.selected_sources.length - 1 && (
                                <span className="source-route-arrow" aria-hidden="true">→</span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="no-source-note">
                        No source was selected because the request must be clarified or is unsupported.
                      </p>
                    )}

                    {(selectionPlan.entities.length > 0 || selectionPlan.approved_terms.length > 0) && (
                      <div className="selection-facts">
                        {selectionPlan.entities.length > 0 && (
                          <article>
                            <strong>Detected entities</strong>
                            <div className="definition-tags">
                              {selectionPlan.entities.map((entity) => (
                                <code key={`${entity.entity_type}-${entity.value}`}>
                                  {displayEntityType(entity.entity_type)}: {entity.value}
                                </code>
                              ))}
                            </div>
                          </article>
                        )}

                        {selectionPlan.approved_terms.length > 0 && (
                          <article>
                            <strong>Approved meanings</strong>
                            <div className="definition-tags">
                              {selectionPlan.approved_terms.map((term) => (
                                <button className="definition-chip" type="button" key={term.slug} onClick={showBusinessMeaning}>
                                  {term.term} - {term.version}
                                </button>
                              ))}
                            </div>
                          </article>
                        )}
                      </div>
                    )}

                    {selectionPlan.clarification_options.length > 0 && (
                      <div className="clarification-box">
                        <strong>Clarify the approved meaning</strong>
                        <div>
                          {selectionPlan.clarification_options.map((option) => (
                            <span key={option}>{option}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    {selectionPlan.evidence_requirements.length > 0 && (
                      <div className="requirement-list">
                        {selectionPlan.evidence_requirements.map((requirement) => (
                          <article className="requirement-card" key={`${requirement.source}-${requirement.need}`}>
                            <span>{displaySource(requirement.source)}</span>
                            <strong>{requirement.need}</strong>
                            <p>{requirement.reason}</p>
                            {requirement.fields.length > 0 && (
                              <div className="definition-tags">
                                {requirement.fields.map((field) => (
                                  <code key={`${requirement.source}-${field}`}>{field}</code>
                                ))}
                              </div>
                            )}
                          </article>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>
            )}

            {/* Connected Evidence: invoice record next to the documents linked to it by ID */}
            {activeTab === "connected" && (
            <section className="linked-evidence" aria-labelledby="linked-heading">
              <div className="table-heading inline-heading">
                <div>
                  <p className="section-label">Connected evidence</p>
                  <h2 id="linked-heading">Connect a record to its evidence</h2>
                </div>
                <span>ID-based join</span>
              </div>

              <div className="linked-body">
                <div className="linked-control-panel">
                  <form className="linked-form" onSubmit={submitLinkedInvoiceEvidence}>
                    <label htmlFor="linked-invoice-id">Invoice ID</label>
                    <div className="linked-actions">
                      <input
                        id="linked-invoice-id"
                        name="linked-invoice-id"
                        value={linkedInvoiceInput}
                        onChange={(event) => setLinkedInvoiceInput(event.target.value)}
                        placeholder="INV5004"
                        maxLength={7}
                        autoComplete="off"
                      />
                      <button className="primary-button" type="submit">
                        Connect
                      </button>
                      <button className="secondary-button" type="button" onClick={clearLinkedInvoiceEvidence}>
                        Clear
                      </button>
                    </div>
                  </form>
                </div>

                <div className="linked-prompts" aria-label="Sample linked evidence records">
                  {["INV5004", "INV5003", "INV5008"].map((invoiceId) => (
                    <button
                      className="linked-prompt"
                      key={invoiceId}
                      type="button"
                      onClick={() => loadLinkedInvoiceEvidence(invoiceId)}
                    >
                      {invoiceId}
                    </button>
                  ))}
                </div>

                {isLinkedEvidenceLoading && (
                  <div className="mini-state" aria-live="polite">
                    <span className="spinner small-spinner" aria-hidden="true" />
                    Connecting structured record to document metadata...
                  </div>
                )}

                {linkedEvidenceError && (
                  <div className="mini-state error-text" role="alert">
                    {linkedEvidenceError}
                  </div>
                )}

                {linkedEvidence && !isLinkedEvidenceLoading && (
                  <div className="linked-result">
                    <div className="linked-answer-heading">
                      <div>
                        <span className={`answer-status ${linkedEvidence.status === "linked" ? "answered" : "no_evidence"}`}>
                          {linkedEvidence.status === "linked" ? "Linked evidence" : "Missing link"}
                        </span>
                        <h3>{linkedEvidence.answer}</h3>
                      </div>
                    </div>

                    <div className="connection-flow">
                      <article className="connection-card record-card">
                        <span>Structured record</span>
                        <strong>{linkedEvidence.structured_facts.invoice_id}</strong>
                        <dl className="record-facts">
                          <div>
                            <dt>Project / property</dt>
                            <dd>{linkedEvidence.structured_facts.project_id} / {linkedEvidence.structured_facts.property_id}</dd>
                          </div>
                          <div>
                            <dt>Vendor</dt>
                            <dd>{linkedEvidence.structured_facts.vendor_id}</dd>
                          </div>
                          <div>
                            <dt>PO / cost code</dt>
                            <dd>{linkedEvidence.structured_facts.po_id} / {linkedEvidence.structured_facts.cost_code}</dd>
                          </div>
                          <div>
                            <dt>Status</dt>
                            <dd>{displayStatus(linkedEvidence.structured_facts.status)}</dd>
                          </div>
                          <div>
                            <dt>PO variance</dt>
                            <dd>{formatCurrency(linkedEvidence.structured_facts.po_variance_amount, linkedEvidence.structured_facts.currency)}</dd>
                          </div>
                          <div>
                            <dt>Outstanding</dt>
                            <dd>{formatCurrency(linkedEvidence.structured_facts.outstanding_amount, linkedEvidence.structured_facts.currency)}</dd>
                          </div>
                        </dl>
                      </article>

                      <div className="flow-arrow" aria-hidden="true">→</div>

                      <article className="connection-card proof-card">
                        <span>Link proof</span>
                        <strong>
                          {linkedEvidence.sources.length > 0 ? "Stable IDs match" : "No record-level match"}
                        </strong>
                        {linkedEvidence.sources.length > 0 ? (
                          <ul>
                            {linkedEvidence.sources[0].matched_identifiers.map((identifier) => (
                              <li key={identifier}>
                                {describeMatchedIdentifier(identifier, linkedEvidence.structured_facts)}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p>No document shares the invoice, PO, or enough record-level business IDs.</p>
                        )}
                      </article>

                      <div className="flow-arrow" aria-hidden="true">→</div>

                      <article className="connection-card source-card">
                        <span>Source evidence</span>
                        {linkedEvidence.sources.length > 0 ? (
                          <strong>{linkedEvidence.sources[0].metadata.document_id}</strong>
                        ) : (
                          <strong>Missing document link</strong>
                        )}
                        <p>
                          {linkedEvidence.sources.length > 0
                            ? `${linkedEvidence.sources[0].metadata.document_type}${
                                linkedEvidence.sources[0].metadata.document_date
                                  ? ` - ${formatDate(linkedEvidence.sources[0].metadata.document_date)}`
                                  : ""
                              }`
                            : "The record remains visible, but no source passage is attached."}
                        </p>
                      </article>
                    </div>

                    {linkedEvidence.sources.length > 0 ? (
                      <div className="linked-source-list">
                        {linkedEvidence.sources.map((source) => (
                          <article className="evidence-card linked-card" key={source.chunk_id}>
                            <div>
                              <strong>{source.metadata.document_id}</strong>
                              <span>
                                {source.metadata.document_type}
                                {source.metadata.document_date
                                  ? ` - ${formatDate(source.metadata.document_date)}`
                                  : ""}
                              </span>
                            </div>
                            <p>{source.text}</p>
                            <code>
                              Matched IDs: {source.matched_identifiers
                                .map((identifier) => describeMatchedIdentifier(identifier, linkedEvidence.structured_facts))
                                .join(" / ")}
                            </code>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="no-source-note">
                        The structured record exists, but no document passage has a matching stable identifier.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </section>
            )}

            {/* Relationship Graph: Neo4j paths for PO variance invoices, with missing-document cases flagged */}
            {activeTab === "relationships" && (
            <section className="relationship-paths" aria-labelledby="relationship-heading">
              <div className="table-heading inline-heading">
                <div>
                  <p className="section-label">Relationship graph</p>
                  <h2 id="relationship-heading">Trace PO variance paths</h2>
                </div>
                <span>Neo4j + Cypher</span>
              </div>

              <div className="relationship-body">
                <div className="relationship-control-panel">
                  <form className="relationship-form" onSubmit={submitRelationshipPaths}>
                    <label htmlFor="relationship-property-id">Property ID</label>
                    <div className="relationship-actions">
                      <input
                        id="relationship-property-id"
                        name="relationship-property-id"
                        value={relationshipPropertyInput}
                        onChange={(event) => setRelationshipPropertyInput(event.target.value)}
                        placeholder="P204"
                        maxLength={4}
                        autoComplete="off"
                      />
                      <button className="primary-button" type="submit">
                        Trace
                      </button>
                      <button className="secondary-button" type="button" onClick={clearRelationshipPaths}>
                        Clear
                      </button>
                    </div>
                  </form>
                </div>

                <div className="linked-prompts" aria-label="Sample relationship path properties">
                  {["P204", "P205", "P999"].map((propertyId) => (
                    <button
                      className="linked-prompt"
                      key={propertyId}
                      type="button"
                      onClick={() => loadRelationshipPaths(propertyId)}
                    >
                      {propertyId}
                    </button>
                  ))}
                </div>

                {isRelationshipLoading && (
                  <div className="mini-state" aria-live="polite">
                    <span className="spinner small-spinner" aria-hidden="true" />
                    Running Cypher traversal in Neo4j...
                  </div>
                )}

                {relationshipError && (
                  <div className="mini-state error-text" role="alert">
                    {relationshipError}
                  </div>
                )}

                {relationshipPaths && !isRelationshipLoading && (
                  <div className="relationship-result">
                    <div className="linked-answer-heading">
                      <div>
                        <span className="answer-status answered">
                          Relationship trace
                        </span>
                        <h3>{relationshipPaths.answer}</h3>
                      </div>
                    </div>

                    {relationshipPaths.paths.length > 0 ? (
                      <div className="path-list">
                        {relationshipPaths.paths.map((path) => (
                          <article className="path-card" key={`${path.invoice_id}-${path.document_id ?? "missing"}`}>
                            <div className="path-card-heading">
                              <div>
                                <strong>{path.finding}</strong>
                                <span>
                                  {formatCurrency(path.variance_amount, "INR")} variance / {path.status === "supported" ? "Evidence linked" : "Missing evidence"}
                                </span>
                                <button className="definition-chip path-definition-chip" type="button" onClick={showBusinessMeaning}>
                                  {definitionLabel(poVarianceDefinition, "PO variance - v0.6")}
                                </button>
                              </div>
                              <span className={`path-status ${path.status}`}>
                                {path.status === "supported" ? "Supported" : "Missing evidence"}
                              </span>
                            </div>

                            <div className="path-trace" aria-label={`Relationship path for ${path.invoice_id}`}>
                              {path.nodes.map((node, index) => (
                                <span className="path-node-wrap" key={`${path.invoice_id}-${node.label}-${node.id}`}>
                                  <span className="path-node">
                                    <small>{node.label}</small>
                                    {node.display}
                                  </span>
                                  {index < path.nodes.length - 1 && (
                                    <span className="path-arrow" aria-hidden="true">→</span>
                                  )}
                                </span>
                              ))}
                            </div>

                            <details className="path-details">
                              <summary>Show relationship edges</summary>
                              <div className="path-edge-list">
                                {path.edges.map((edge) => (
                                  <code key={`${path.invoice_id}-${edge.type}-${edge.from}-${edge.to}`}>
                                    {edge.from} -[{edge.type}]-&gt; {edge.to}
                                  </code>
                                ))}
                              </div>
                            </details>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="no-source-note">
                        No PO variance relationship paths were returned for this property.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </section>
            )}

            {/* Document Evidence: grounded answer with the retrieved passages and their metadata */}
            {activeTab === "documents" && (
            <section className="document-evidence" aria-labelledby="document-heading">
              <div className="table-heading inline-heading">
                <div>
                  <p className="section-label">Document evidence</p>
                  <h2 id="document-heading">Document evidence search</h2>
                </div>
                <span>{projectFilter ? `Scoped to ${projectFilter}` : "All documents"}</span>
              </div>

              <div className="document-body">
                <form className="document-form" onSubmit={submitDocumentQuestion}>
                  <label htmlFor="document-question">Question</label>
                  <div className="document-actions">
                    <input
                      id="document-question"
                      name="document-question"
                      value={documentQuestion}
                      onChange={(event) => setDocumentQuestion(event.target.value)}
                      placeholder="Ask a document evidence question"
                      autoComplete="off"
                    />
                    <button className="primary-button" type="submit">
                      Ask
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={clearDocumentQuestion}
                    >
                      Clear
                    </button>
                  </div>
                </form>

                <div className="document-prompts" aria-label="Sample document questions">
                  {DOCUMENT_QUESTIONS.map((prompt) => (
                    <button
                      className="document-prompt"
                      key={prompt.question}
                      type="button"
                      onClick={() => selectDocumentQuestion(prompt.question)}
                    >
                      <span>{prompt.label}</span>
                      {prompt.question}
                    </button>
                  ))}
                </div>

                {isDocumentLoading && (
                  <div className="mini-state" aria-live="polite">
                    <span className="spinner small-spinner" aria-hidden="true" />
                    Retrieving document evidence...
                  </div>
                )}

                {documentError && (
                  <div className="mini-state error-text" role="alert">
                    {documentError}
                  </div>
                )}

                {documentAnswer && !isDocumentLoading && (
                  <div className="answer-card">
                    <div className="answer-heading">
                      <div>
                        <span className={`answer-status ${documentAnswer.status}`}>
                          {documentAnswer.status === "answered" ? "Grounded answer" : "No evidence"}
                        </span>
                        <h3>{documentAnswer.answer}</h3>
                      </div>
                      <small>
                        Confidence {Math.round(documentAnswer.confidence * 100)}% ·{" "}
                        {documentAnswer.latency_ms} ms
                      </small>
                    </div>

                    {documentAnswer.sources.length > 0 ? (
                      <>
                        <div className="source-summary">
                          <strong>{documentAnswer.sources.length} source reference{documentAnswer.sources.length === 1 ? "" : "s"}</strong>
                          <span>Document passages used for review</span>
                        </div>
                        
                      <div className="evidence-grid">
                        {documentAnswer.sources.map((source) => (
                          <article className="evidence-card" key={source.chunk_id}>
                            <div>
                              <strong>{source.metadata.document_id}</strong>
                              <span>
                                {source.metadata.document_type}
                                {source.metadata.document_date
                                  ? ` · ${formatDate(source.metadata.document_date)}`
                                  : ""}
                              </span>
                            </div>
                            <p>{source.text}</p>
                            <code>
                              {[source.metadata.project_id, source.metadata.invoice_id, source.metadata.po_id]
                                .filter(Boolean)
                                .join(" · ") || source.metadata.source_file}
                            </code>
                          </article>
                        ))}
                      </div>
                      </>
                    ) : (
                      <p className="no-source-note">
                        No supporting passage was returned.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </section>
            )}

            {/* Invoice register table, shown under Structured Checks with or without a project filter */}
            {activeTab === "structured" && (
            <div className="table-card">
              <div className="table-heading">
                <div>
                  <p className="section-label">Structured response</p>
                  <h2>Invoice register</h2>
                </div>
                <span>{data.count} record{data.count === 1 ? "" : "s"}</span>
              </div>

              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Invoice</th>
                      <th>Project &amp; property</th>
                      <th>Vendor</th>
                      <th>PO &amp; cost code</th>
                      <th className="numeric">Invoice amount</th>
                      <th className="numeric">Outstanding</th>
                      <th>Status</th>
                      <th>Due date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((invoice) => (
                      <tr key={invoice.invoice_id}>
                        <td>
                          <strong>{invoice.invoice_number}</strong>
                          <code>{invoice.invoice_id}</code>
                        </td>
                        <td>
                          <strong>{invoice.project.name}</strong>
                          <span className="property-line">
                            {invoice.project.project_id} - {invoice.property.name}
                            <button
                              aria-label={`${invoice.property.name} property details`}
                              className="info-chip"
                              type="button"
                            >
                              i
                              <span className="tooltip" role="tooltip">
                                City: {invoice.property.city}
                                <br />
                                Type: {invoice.property.property_type}
                                <br />
                                Status: {invoice.property.status}
                              </span>
                            </button>
                          </span>
                          <code>{invoice.property.property_id}</code>
                        </td>
                        <td>
                          <strong>{invoice.vendor.name}</strong>
                          <code>{invoice.vendor.vendor_id} / {invoice.vendor.tax_id}</code>
                          <span>{invoice.vendor.category} ({invoice.vendor.city})</span>
                        </td>
                        <td>
                          <strong>{invoice.purchase_order.po_id}</strong>
                          <code>{invoice.budget.cost_code}</code>
                        </td>
                        <td className="numeric amount">
                          {formatCurrency(invoice.amount, invoice.currency)}
                        </td>
                        <td className="numeric amount">
                          {formatCurrency(invoice.outstanding_amount, invoice.currency)}
                        </td>
                        <td>
                          <span className={`status status-${invoice.status.toLowerCase()}`}>
                            {displayStatus(invoice.status)}
                          </span>
                        </td>
                        <td>{formatDate(invoice.due_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            )}
          </section>
        )}
      </main>

      <footer>
        <span>Day 9 challenge benchmark</span>
        <span>Validated plan - Selected source execution - Evidence trace</span>
      </footer>
    </div>
  );
}

export default App;
