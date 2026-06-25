def process_large_file(filepath):
    with open(filepath, 'r') as f:
        data = f.read()
    lines = data.split('\n')
    results = []
    for line in lines:
        results.append(line.upper())
    return results
