import heapq


def dijkstra(start, goal, adjacency, base_edges, closed_edges, delay_edges):
    if start == goal:
        return [start], 0
    queue, visited, prev = [(0, start, None)], {}, {}
    while queue:
        cost, node, parent = heapq.heappop(queue)
        if node in visited:
            continue
        visited[node], prev[node] = cost, parent
        if node == goal:
            break
        for neighbor in adjacency.get(node, ()):
            edge = (node, neighbor)
            if edge in closed_edges or edge not in base_edges:
                continue
            heapq.heappush(queue, (cost + base_edges[edge] + delay_edges.get(edge, 0), neighbor, node))
    if goal not in visited:
        return [], None
    path, node = [], goal
    while node is not None:
        path.append(node)
        node = prev[node]
    return path[::-1], visited[goal]
