import sys
import os
import pulp

# Add backend to path if needed or just rely on venv
# Try to find the license
cwd = os.getcwd()
lic_path = os.path.join(cwd, "gurobi.lic")
print(f"Checking for license at: {lic_path}")
if os.path.exists(lic_path):
    os.environ["GRB_LICENSE_FILE"] = lic_path
    print("License file found and env var set.")
else:
    print("License file NOT found in CWD.")

print(f"Python: {sys.version}")
print(f"PuLP version: {pulp.__version__}")

def test_solver():
    print("\nTesting Gurobi Solver...")
    try:
        prob = pulp.LpProblem("Test", pulp.LpMinimize)
        x = pulp.LpVariable("x", 0, 10)
        prob += x >= 5
        prob += x
        
        solver = pulp.GUROBI(msg=1)
        prob.solve(solver)
        
        print(f"Status: {pulp.LpStatus[prob.status]}")
        print(f"Value: {pulp.value(x)}")
        
        if pulp.LpStatus[prob.status] == "Optimal":
            print("Gurobi test PASSED.")
        else:
            print("Gurobi test FAILED (Non-optimal status).")
            
    except Exception as e:
        print(f"Gurobi test FAILED with exception: {e}")

if __name__ == "__main__":
    test_solver()
