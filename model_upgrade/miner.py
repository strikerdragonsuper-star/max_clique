import asyncio
import time
import typing
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import bittensor as bt
from CliqueAI.graph.codec import GraphCodec
from CliqueAI.protocol import MaximumCliqueOfLambdaGraph
from common.base.miner import BaseMinerNeuron

from model_upgrade.solver import fallback_maximum_clique, solve_maximum_clique
from model_upgrade.validator_store import build_validator_record, save_validator_record

# Reserve a little wall-clock time for axon serialization/network.
SOLVE_RESPONSE_MARGIN_SECONDS = 0.15
# Absolute cap so a stuck worker cannot block the executor forever.
SAFETY_SOLVE_TIMEOUT_SECONDS = 120.0


def _solve_before_deadline(
    response_deadline: float,
    number_of_nodes: int,
    adjacency_list: list[list[int]],
    time_limit: float,
) -> list[int]:
    """Run the solver with only the time left when this job actually starts."""
    remaining = response_deadline - time.perf_counter()
    if remaining <= 0.2:
        return fallback_maximum_clique(adjacency_list)

    effective_limit = min(time_limit, remaining)
    return solve_maximum_clique(
        number_of_nodes,
        adjacency_list,
        time_limit=effective_limit,
    )


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self._solve_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="clique-solve",
        )
        self.axon.attach(
            forward_fn=self.forward_graph,
            blacklist_fn=self.backlist_graph,
            priority_fn=self.priority_graph,
        )

    def __exit__(self, exc_type, exc_value, traceback):
        self._solve_executor.shutdown(wait=False, cancel_futures=True)
        return super().__exit__(exc_type, exc_value, traceback)

    async def forward_graph(
        self, synapse: MaximumCliqueOfLambdaGraph
    ) -> MaximumCliqueOfLambdaGraph:
        codec = GraphCodec()
        adjacency_matrix = codec.decode_matrix(synapse.encoded_matrix)
        adjacency_list = codec.matrix_to_list(adjacency_matrix)
        time_limit = float(synapse.timeout) if synapse.timeout else 30.0
        response_deadline = time.perf_counter() + time_limit - SOLVE_RESPONSE_MARGIN_SECONDS
        bt.logging.info(
            f"Solving maximum clique: nodes={synapse.number_of_nodes}, "
            f"timeout={time_limit}s, uuid={synapse.uuid}"
        )

        validator_hotkey = (
            synapse.dendrite.hotkey
            if synapse.dendrite is not None and synapse.dendrite.hotkey
            else None
        )

        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        solve_future = loop.run_in_executor(
            self._solve_executor,
            _solve_before_deadline,
            response_deadline,
            synapse.number_of_nodes,
            adjacency_list,
            time_limit,
        )

        safety_timeout = max(time_limit + 30.0, SAFETY_SOLVE_TIMEOUT_SECONDS)
        try:
            maximum_clique = await asyncio.wait_for(solve_future, timeout=safety_timeout)
        except asyncio.TimeoutError:
            bt.logging.warning(
                f"Solve safety timeout ({safety_timeout:.0f}s) for uuid={synapse.uuid}; "
                "returning fallback clique"
            )
            maximum_clique = fallback_maximum_clique(adjacency_list)

        elapsed = time.perf_counter() - start

        bt.logging.info(
            f"Maximum clique found: {maximum_clique} with size {len(maximum_clique)}"
        )
        synapse.maximum_clique = maximum_clique

        record = build_validator_record(
            synapse,
            elapsed_seconds=elapsed,
            validator_hotkey=validator_hotkey,
        )
        asyncio.create_task(self._persist_validator_record(record))

        return synapse

    async def _persist_validator_record(self, record: dict[str, Any]) -> None:
        try:
            saved = await asyncio.to_thread(save_validator_record, record)
            if saved is not None:
                bt.logging.info(f"Saved validator query to {saved}")
        except Exception:
            bt.logging.error("Failed to save validator data", exc_info=True)

    async def backlist_graph(
        self, synapse: MaximumCliqueOfLambdaGraph
    ) -> typing.Tuple[bool, str]:
        return await self.blacklist(synapse)

    async def priority_graph(self, synapse: MaximumCliqueOfLambdaGraph) -> float:
        return await self.priority(synapse)


if __name__ == "__main__":
    with Miner() as miner:
        bt.logging.info("Miner has started running.")
        while True:
            if miner.should_exit:
                bt.logging.info("Miner is exiting.")
                break
            time.sleep(1)
