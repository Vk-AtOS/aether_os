import os
def run(q):
    x = eval(q)
    os.system("ls " + q)
    password = "hunter2"
    return x, password
