"""
Leiden Clustering Engine - Phase 1 of the reconciliation pipeline.

Builds affinity graph and partitions into solvable clusters using
the Leiden algorithm for community detection.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Dict, Set, Tuple, Optional
import math

import numpy as np
import igraph as ig
import leidenalg
import structlog

from ..config import get_settings
from ..models import (
    Transaction,
    TransactionMatch,
    AuditEntry,
    AuditAction,
)

logger = structlog.get_logger()


@dataclass
class Cluster:
    """A cluster of related transactions."""
    id: str
    invoices: List[Transaction] = field(default_factory=list)
    payments: List[Transaction] = field(default_factory=list)
    edges: List[TransactionMatch] = field(default_factory=list)
    total_invoice_cents: int = 0
    total_payment_cents: int = 0

    @property
    def size(self) -> int:
        return len(self.invoices) + len(self.payments)

    @property
    def is_balanced(self) -> bool:
        """Check if cluster has both invoices and payments."""
        return len(self.invoices) > 0 and len(self.payments) > 0


@dataclass
class ClusteringResult:
    """Result of clustering phase."""
    clusters: List[Cluster]
    orphan_invoices: List[Transaction]
    orphan_payments: List[Transaction]
    audit_entries: List[AuditEntry]
    stats: Dict[str, any]


class LeidenClusterEngine:
    """
    Phase 1: Graph-based clustering using Leiden algorithm.

    Builds an affinity graph where:
    - Nodes are transactions (invoices and payments)
    - Edges connect potentially related transactions
    - Edge weights encode semantic similarity × temporal proximity

    Uses Leiden algorithm for community detection to find dense clusters.
    """

    def __init__(self):
        self.settings = get_settings()
        self.max_cluster_size = self.settings.max_cluster_size
        self.resolution = self.settings.leiden_resolution
        self.temporal_decay = self.settings.temporal_decay_alpha
        self.min_edge_weight = 0.1  # Minimum weight to create edge

    def process(
        self,
        invoices: List[Transaction],
        payments: List[Transaction],
    ) -> ClusteringResult:
        """
        Cluster transactions using Leiden algorithm.

        Args:
            invoices: Remaining invoice transactions
            payments: Remaining payment transactions

        Returns:
            ClusteringResult with clusters and orphans
        """
        logger.info(
            "Starting clustering",
            invoices=len(invoices),
            payments=len(payments),
        )

        if not invoices or not payments:
            return ClusteringResult(
                clusters=[],
                orphan_invoices=invoices,
                orphan_payments=payments,
                audit_entries=[],
                stats={"clusters": 0},
            )

        # Build affinity graph
        graph, node_map, edges = self._build_affinity_graph(invoices, payments)

        if graph.vcount() == 0:
            return ClusteringResult(
                clusters=[],
                orphan_invoices=invoices,
                orphan_payments=payments,
                audit_entries=[],
                stats={"clusters": 0, "no_edges": True},
            )

        # Run Leiden algorithm
        partition = leidenalg.find_partition(
            graph,
            leidenalg.ModularityVertexPartition,
            weights="weight",
            n_iterations=-1,  # Run until convergence
            seed=42,  # Reproducibility
        )

        # Convert partition to clusters
        clusters = self._partition_to_clusters(
            partition, node_map, invoices, payments, edges
        )

        # Handle oversized clusters
        clusters = self._split_large_clusters(clusters)

        # Identify orphans (nodes not in any cluster)
        clustered_invoice_ids = set()
        clustered_payment_ids = set()
        for cluster in clusters:
            clustered_invoice_ids.update(inv.id for inv in cluster.invoices)
            clustered_payment_ids.update(pay.id for pay in cluster.payments)

        orphan_invoices = [inv for inv in invoices if inv.id not in clustered_invoice_ids]
        orphan_payments = [pay for pay in payments if pay.id not in clustered_payment_ids]

        # Audit
        audit_entries = [
            AuditEntry(
                action=AuditAction.CLUSTER_CREATED,
                cluster_id=cluster.id,
                message=f"Cluster created with {cluster.size} nodes",
                details={
                    "invoices": len(cluster.invoices),
                    "payments": len(cluster.payments),
                    "edges": len(cluster.edges),
                },
            )
            for cluster in clusters
        ]

        stats = {
            "total_clusters": len(clusters),
            "avg_cluster_size": np.mean([c.size for c in clusters]) if clusters else 0,
            "max_cluster_size": max(c.size for c in clusters) if clusters else 0,
            "orphan_invoices": len(orphan_invoices),
            "orphan_payments": len(orphan_payments),
            "modularity": partition.modularity if partition else 0,
        }

        logger.info("Clustering complete", **stats)

        return ClusteringResult(
            clusters=clusters,
            orphan_invoices=orphan_invoices,
            orphan_payments=orphan_payments,
            audit_entries=audit_entries,
            stats=stats,
        )

    def _build_affinity_graph(
        self,
        invoices: List[Transaction],
        payments: List[Transaction],
    ) -> Tuple[ig.Graph, Dict[str, int], List[TransactionMatch]]:
        """
        Build affinity graph from transactions.

        Returns:
            Tuple of (igraph.Graph, node_id_to_index_map, edge_list)
        """
        # Create node mapping
        all_txns = invoices + payments
        node_map = {txn.id: i for i, txn in enumerate(all_txns)}

        # Create edges
        edges = []
        edge_tuples = []
        edge_weights = []

        for inv in invoices:
            for pay in payments:
                weight = self._calculate_edge_weight(inv, pay)

                if weight >= self.min_edge_weight:
                    match = TransactionMatch(
                        invoice_id=inv.id,
                        payment_id=pay.id,
                        semantic_score=self._semantic_similarity(inv, pay),
                        temporal_score=self._temporal_similarity(inv, pay),
                        combined_score=weight,
                        amount_difference_cents=abs(inv.amount_cents - pay.amount_cents),
                        days_apart=self._days_between(inv, pay),
                    )
                    edges.append(match)
                    edge_tuples.append((node_map[inv.id], node_map[pay.id]))
                    edge_weights.append(weight)

        # Create graph
        graph = ig.Graph(n=len(all_txns), edges=edge_tuples, directed=False)
        graph.es["weight"] = edge_weights

        # Add node attributes
        graph.vs["txn_id"] = [txn.id for txn in all_txns]
        graph.vs["is_invoice"] = [i < len(invoices) for i in range(len(all_txns))]

        return graph, node_map, edges

    def _calculate_edge_weight(
        self,
        invoice: Transaction,
        payment: Transaction,
    ) -> float:
        """
        Calculate edge weight combining semantic and temporal factors.

        W_ij = Score_NLP(i,j) × 1/(1 + α × |t_i - t_j|)
        """
        semantic = self._semantic_similarity(invoice, payment)
        temporal = self._temporal_similarity(invoice, payment)

        # Combined weight
        weight = semantic * temporal

        # Boost for amount proximity
        amount_diff_ratio = abs(invoice.amount_cents - payment.amount_cents) / max(
            invoice.amount_cents, payment.amount_cents, 1
        )
        if amount_diff_ratio < 0.01:  # Within 1%
            weight *= 1.5
        elif amount_diff_ratio < 0.05:  # Within 5%
            weight *= 1.2

        return min(1.0, weight)

    def _semantic_similarity(
        self,
        txn1: Transaction,
        txn2: Transaction,
    ) -> float:
        """Calculate semantic similarity using embeddings or text."""
        # Use embeddings if available
        if txn1.embedding is not None and txn2.embedding is not None:
            # Cosine similarity
            dot = np.dot(txn1.embedding, txn2.embedding)
            norm1 = np.linalg.norm(txn1.embedding)
            norm2 = np.linalg.norm(txn2.embedding)
            if norm1 > 0 and norm2 > 0:
                return float((dot / (norm1 * norm2) + 1) / 2)  # Normalize to 0-1

        # Fallback to simple text matching
        score = 0.0
        comparisons = 0

        if txn1.counterparty_name and txn2.counterparty_name:
            from rapidfuzz import fuzz
            score += fuzz.token_sort_ratio(
                txn1.counterparty_name.lower(),
                txn2.counterparty_name.lower(),
            ) / 100.0
            comparisons += 1

        if txn1.counterparty_rfc and txn2.counterparty_rfc:
            if txn1.counterparty_rfc.upper() == txn2.counterparty_rfc.upper():
                score += 1.0
            comparisons += 1

        return score / comparisons if comparisons > 0 else 0.3

    def _temporal_similarity(
        self,
        txn1: Transaction,
        txn2: Transaction,
    ) -> float:
        """
        Calculate temporal similarity with decay.

        Returns 1/(1 + α × days_apart)
        """
        days = self._days_between(txn1, txn2)
        return 1.0 / (1.0 + self.temporal_decay * days)

    def _days_between(
        self,
        txn1: Transaction,
        txn2: Transaction,
    ) -> int:
        """Calculate days between two transactions."""
        if txn1.transaction_date is None or txn2.transaction_date is None:
            return 30  # Default assumption
        return abs((txn1.transaction_date - txn2.transaction_date).days)

    def _partition_to_clusters(
        self,
        partition: leidenalg.VertexPartition,
        node_map: Dict[str, int],
        invoices: List[Transaction],
        payments: List[Transaction],
        edges: List[TransactionMatch],
    ) -> List[Cluster]:
        """Convert Leiden partition to Cluster objects."""
        # Create reverse map
        index_to_txn = {}
        for inv in invoices:
            index_to_txn[node_map[inv.id]] = inv
        for pay in payments:
            index_to_txn[node_map[pay.id]] = pay

        # Group nodes by community
        communities = {}
        for node_idx, community_idx in enumerate(partition.membership):
            if community_idx not in communities:
                communities[community_idx] = []
            communities[community_idx].append(node_idx)

        # Create clusters
        clusters = []
        for comm_idx, node_indices in communities.items():
            cluster_invoices = []
            cluster_payments = []
            cluster_txn_ids = set()

            for node_idx in node_indices:
                txn = index_to_txn.get(node_idx)
                if txn:
                    cluster_txn_ids.add(txn.id)
                    if node_idx < len(invoices):
                        cluster_invoices.append(txn)
                    else:
                        cluster_payments.append(txn)

            # Skip empty or single-type clusters
            if not cluster_invoices or not cluster_payments:
                continue

            # Get edges within cluster
            cluster_edges = [
                e for e in edges
                if e.invoice_id in cluster_txn_ids and e.payment_id in cluster_txn_ids
            ]

            cluster = Cluster(
                id=f"cluster_{comm_idx}",
                invoices=cluster_invoices,
                payments=cluster_payments,
                edges=cluster_edges,
                total_invoice_cents=sum(inv.amount_cents for inv in cluster_invoices),
                total_payment_cents=sum(pay.amount_cents for pay in cluster_payments),
            )
            clusters.append(cluster)

        return clusters

    def _split_large_clusters(
        self,
        clusters: List[Cluster],
    ) -> List[Cluster]:
        """Split clusters that exceed max size."""
        result = []

        for cluster in clusters:
            if cluster.size <= self.max_cluster_size:
                result.append(cluster)
            else:
                # Recursively split using higher resolution
                sub_clusters = self._split_cluster(cluster)
                result.extend(sub_clusters)

        return result

    def _split_cluster(
        self,
        cluster: Cluster,
        depth: int = 0,
    ) -> List[Cluster]:
        """Split a large cluster using min-cut or higher resolution."""
        if cluster.size <= self.max_cluster_size or depth > 3:
            return [cluster]

        # Build sub-graph
        all_txns = cluster.invoices + cluster.payments
        node_map = {txn.id: i for i, txn in enumerate(all_txns)}

        edge_tuples = []
        edge_weights = []
        for edge in cluster.edges:
            if edge.invoice_id in node_map and edge.payment_id in node_map:
                edge_tuples.append((node_map[edge.invoice_id], node_map[edge.payment_id]))
                edge_weights.append(edge.combined_score)

        if not edge_tuples:
            return [cluster]

        graph = ig.Graph(n=len(all_txns), edges=edge_tuples, directed=False)
        graph.es["weight"] = edge_weights

        # Use higher resolution to split
        higher_resolution = self.resolution * (2 ** (depth + 1))
        partition = leidenalg.find_partition(
            graph,
            leidenalg.RBConfigurationVertexPartition,
            weights="weight",
            resolution_parameter=higher_resolution,
        )

        if len(set(partition.membership)) <= 1:
            # Couldn't split further
            return [cluster]

        # Create sub-clusters
        sub_clusters = self._partition_to_clusters(
            partition,
            node_map,
            cluster.invoices,
            cluster.payments,
            cluster.edges,
        )

        # Recursively split if needed
        final_clusters = []
        for sub in sub_clusters:
            if sub.size > self.max_cluster_size:
                final_clusters.extend(self._split_cluster(sub, depth + 1))
            else:
                final_clusters.append(sub)

        return final_clusters if final_clusters else [cluster]

    def merge_clusters(
        self,
        cluster1: Cluster,
        cluster2: Cluster,
    ) -> Cluster:
        """Merge two clusters into one."""
        return Cluster(
            id=f"{cluster1.id}+{cluster2.id}",
            invoices=cluster1.invoices + cluster2.invoices,
            payments=cluster1.payments + cluster2.payments,
            edges=cluster1.edges + cluster2.edges,
            total_invoice_cents=cluster1.total_invoice_cents + cluster2.total_invoice_cents,
            total_payment_cents=cluster1.total_payment_cents + cluster2.total_payment_cents,
        )
