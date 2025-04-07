input_file = "qrels2022.txt"
output_file = "qrels2022_binary.txt"

with open(input_file, "r") as infile, open(output_file, "w") as outfile:
    for line in infile:
        parts = line.strip().split()
        if parts[-1] == "1":
            parts[-1] = "0"
        elif parts[-1] == "2":
            parts[-1] = "1"
        outfile.write(" ".join(parts) + "\n")

print("Conversion complete! Saved as", output_file)
