import os
os.chdir(r'C:\Users\Administrator\Desktop\automatic\ccass-debug')
needle = "LONGBRIDGE_ACCESS_TOKEN"
with open(".env") as f:
    for line in f:
        if needle in line and not line.startswith("#"):
            token = line.strip().split("=", 1)[1]
            with open("_lb_token_tmp.txt", "w") as out:
                out.write(token)
            print(f"Written {len(token)} chars to _lb_token_tmp.txt")
            break
