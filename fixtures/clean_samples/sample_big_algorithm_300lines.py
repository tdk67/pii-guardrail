from typing import List, Optional, Tuple

def vector_dot_product(vec_a: List[float], vec_b: List[float]) -> float:
    return sum(x * y for x, y in zip(vec_a, vec_b))

def vector_cross_product(u: List[float], v: List[float]) -> List[float]:
    return [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]

def euclidean_norm(v: List[float]) -> float:
    return sum(x * x for x in v) ** 0.5

def normalize_vector(v: List[float]) -> List[float]:
    mag = euclidean_norm(v)
    if mag == 0.0:
        return [0.0] * len(v)
    return [x / mag for x in v]

def vector_distance(u: List[float], v: List[float]) -> float:
    return euclidean_norm([x - y for x, y in zip(u, v)])

# --- Matrix Operations ---
def transpose_2d_matrix(grid: List[List[float]]) -> List[List[float]]:
    if not grid or not grid[0]:
        return []
    total_rows = len(grid)
    total_cols = len(grid[0])
    transposed = []
    for c in range(total_cols):
        col_values = []
        for r in range(total_rows):
            col_values.append(grid[r][c])
        transposed.append(col_values)
    return transposed

def matrix_trace(square_matrix: List[List[float]]) -> float:
    return sum(square_matrix[i][i] for i in range(len(square_matrix)))

def matrix_scalar_multiply(matrix: List[List[float]], factor: float) -> List[List[float]]:
    return [[elem * factor for elem in row] for row in matrix]

def matrix_multiply(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    rows_a, cols_a = len(a), len(a[0])
    rows_b, cols_b = len(b), len(b[0])
    result = [[0.0 for _ in range(cols_b)] for _ in range(rows_a)]
    for i in range(rows_a):
        for j in range(cols_b):
            for k in range(cols_a):
                result[i][j] += a[i][k] * b[k][j]
    return result

# --- Computational Geometry ---
def polygon_perimeter(vertices: List[Tuple[float, float]]) -> float:
    n = len(vertices)
    if n < 2:
        return 0.0
    perimeter = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = vertices[i][0] - vertices[j][0]
        dy = vertices[i][1] - vertices[j][1]
        perimeter += (dx * dx + dy * dy) ** 0.5
    return perimeter

def polygon_area(vertices: List[Tuple[float, float]]) -> float:
    n = len(vertices)
    if n < 3:
        return 0.0
    accum = 0.0
    for i in range(n):
        j = (i + 1) % n
        accum += vertices[i][0] * vertices[j][1]
        accum -= vertices[j][0] * vertices[i][1]
    return abs(accum) / 2.0

def bounding_box(points: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    return (min_x, min_y, max_x, max_y)

# --- Statistical Methods ---
def calculate_mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def calculate_variance(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = calculate_mean(values)
    return sum((x - avg) ** 2 for x in values) / (len(values) - 1)

def calculate_standard_deviation(values: List[float]) -> float:
    return calculate_variance(values) ** 0.5

def running_moving_average(series: List[float], window_size: int) -> List[float]:
    if not series or window_size <= 0:
        return []
    averages = []
    current_sum = 0.0
    for idx, num in enumerate(series):
        current_sum += num
        if idx >= window_size:
            current_sum -= series[idx - window_size]
            averages.append(current_sum / window_size)
        elif idx == window_size - 1:
            averages.append(current_sum / window_size)
    return averages

def exponential_smoothing(series: List[float], alpha: float) -> List[float]:
    if not series:
        return []
    smoothed = [series[0]]
    for val in series[1:]:
        next_val = alpha * val + (1.0 - alpha) * smoothed[-1]
        smoothed.append(next_val)
    return smoothed

# --- Numerical Calculus & Optimization ---
def trapezoidal_rule(y_points: List[float], delta_x: float) -> float:
    if len(y_points) < 2:
        return 0.0
    interior_sum = sum(y_points[1:-1])
    return delta_x * (0.5 * y_points[0] + interior_sum + 0.5 * y_points[-1])

def simpson_rule(y_points: List[float], delta_x: float) -> float:
    n = len(y_points) - 1
    if n < 2 or n % 2 != 0:
        return trapezoidal_rule(y_points, delta_x)
    odd_sum = sum(y_points[i] for i in range(1, n, 2))
    even_sum = sum(y_points[i] for i in range(2, n, 2))
    return (delta_x / 3.0) * (y_points[0] + 4.0 * odd_sum + 2.0 * even_sum + y_points[n])

def bisection_root_finding(func_evals: List[Tuple[float, float]], tolerance: float = 1e-5) -> Optional[float]:
    for i in range(len(func_evals) - 1):
        x0, y0 = func_evals[i]
        x1, y1 = func_evals[i + 1]
        if y0 * y1 <= 0.0:
            return (x0 + x1) / 2.0
    return None

def linear_interpolation(x_vals: List[float], y_vals: List[float], target_x: float) -> float:
    if target_x <= x_vals[0]:
        return y_vals[0]
    if target_x >= x_vals[-1]:
        return y_vals[-1]
    for i in range(len(x_vals) - 1):
        if x_vals[i] <= target_x <= x_vals[i + 1]:
            fraction = (target_x - x_vals[i]) / (x_vals[i + 1] - x_vals[i])
            return y_vals[i] + fraction * (y_vals[i + 1] - y_vals[i])
    return y_vals[-1]

# --- Sorting & Searching ---
def binary_search(sorted_arr: List[float], target: float) -> int:
    low = 0
    high = len(sorted_arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if abs(sorted_arr[mid] - target) < 1e-9:
            return mid
        elif sorted_arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1

def quicksort(elements: List[float]) -> List[float]:
    if len(elements) <= 1:
        return elements
    pivot = elements[len(elements) // 2]
    left = [x for x in elements if x < pivot]
    middle = [x for x in elements if x == pivot]
    right = [x for x in elements if x > pivot]
    return quicksort(left) + middle + quicksort(right)

def merge_sorted_lists(list_a: List[float], list_b: List[float]) -> List[float]:
    merged = []
    idx_a, idx_b = 0, 0
    while idx_a < len(list_a) and idx_b < len(list_b):
        if list_a[idx_a] <= list_b[idx_b]:
            merged.append(list_a[idx_a])
            idx_a += 1
        else:
            merged.append(list_b[idx_b])
            idx_b += 1
    merged.extend(list_a[idx_a:])
    merged.extend(list_b[idx_b:])
    return merged

# --- Advanced Signal Processing & Optimization ---
def discrete_convolution(signal_x: List[float], kernel_h: List[float]) -> List[float]:
    len_x, len_h = len(signal_x), len(kernel_h)
    if len_x == 0 or len_h == 0:
        return []
    conv_len = len_x + len_h - 1
    output = [0.0] * conv_len
    for i in range(len_x):
        for j in range(len_h):
            output[i + j] += signal_x[i] * kernel_h[j]
    return output

def matrix_determinant_3x3(m: List[List[float]]) -> float:
    if len(m) != 3 or any(len(r) != 3 for r in m):
        return 0.0
    a = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
    b = m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
    c = m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    return a - b + c

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = vector_dot_product(vec_a, vec_b)
    norm_a = euclidean_norm(vec_a)
    norm_b = euclidean_norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

def manhattan_distance(pt_a: Tuple[float, float], pt_b: Tuple[float, float]) -> float:
    return abs(pt_a[0] - pt_b[0]) + abs(pt_a[1] - pt_b[1])

def chebyshev_distance(pt_a: Tuple[float, float], pt_b: Tuple[float, float]) -> float:
    return max(abs(pt_a[0] - pt_b[0]), abs(pt_a[1] - pt_b[1]))

def calculate_covariance(x_vals: List[float], y_vals: List[float]) -> float:
    n = len(x_vals)
    if n != len(y_vals) or n < 2:
        return 0.0
    mean_x = calculate_mean(x_vals)
    mean_y = calculate_mean(y_vals)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals)) / (n - 1)

def pearson_correlation(x_vals: List[float], y_vals: List[float]) -> float:
    cov = calculate_covariance(x_vals, y_vals)
    std_x = calculate_standard_deviation(x_vals)
    std_y = calculate_standard_deviation(y_vals)
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    return cov / (std_x * std_y)

def polynomial_horner_eval(coefficients: List[float], x: float) -> float:
    result = 0.0
    for coeff in coefficients:
        result = result * x + coeff
    return result

def midpoint_integration(y_vals: List[float], step: float) -> float:
    return sum(y_vals) * step

def numerical_gradient_1d(y_vals: List[float], step: float) -> List[float]:
    n = len(y_vals)
    if n < 2 or step <= 0.0:
        return []
    grad = [0.0] * n
    grad[0] = (y_vals[1] - y_vals[0]) / step
    for i in range(1, n - 1):
        grad[i] = (y_vals[i + 1] - y_vals[i - 1]) / (2.0 * step)
    grad[-1] = (y_vals[-1] - y_vals[-2]) / step
    return grad

def clamp_values(values: List[float], lower: float, upper: float) -> List[float]:
    return [max(lower, min(upper, v)) for v in values]

def standard_scale(values: List[float]) -> List[float]:
    if not values:
        return []
    avg = calculate_mean(values)
    std = calculate_standard_deviation(values)
    if std == 0.0:
        return [0.0] * len(values)
    return [(v - avg) / std for v in values]

def min_max_scale(values: List[float]) -> List[float]:
    if not values:
        return []
    min_v, max_v = min(values), max(values)
    diff = max_v - min_v
    if diff == 0.0:
        return [0.0] * len(values)
    return [(v - min_v) / diff for v in values]

def linear_regression_line(x_coords: List[float], y_coords: List[float]) -> Tuple[float, float]:
    n = len(x_coords)
    if n != len(y_coords) or n < 2:
        return (0.0, 0.0)
    mean_x = calculate_mean(x_coords)
    mean_y = calculate_mean(y_coords)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_coords, y_coords))
    var_x = sum((x - mean_x) ** 2 for x in x_coords)
    if var_x == 0.0:
        return (0.0, mean_y)
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return (slope, intercept)

def cumulative_sum(values: List[float]) -> List[float]:
    running_total = 0.0
    totals = []
    for val in values:
        running_total += val
        totals.append(running_total)
    return totals
