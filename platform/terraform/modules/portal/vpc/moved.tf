# State moves for #1134.
#
# The private-tier IPv4 default route collapses from two mutually-exclusive
# resources into one persistent owner:
#
#   - aws_route.private_nat                 (main.tf,       inspection OFF)
#   - aws_route.private_default_via_firewall (inspection.tf, inspection ON)
#
# both become aws_route.private_default (main.tf), whose target is chosen by
# enable_portal_inspection. In any given deployed state exactly ONE of the two
# historical resources exists, so preserving state identity means reconciling
# whichever one is present onto the new address.
#
# Two historical addresses converge on one new address. Two direct moves to the
# same destination are ambiguous to Terraform, so this is a CHAIN through one
# historical address:
#
#   private_default_via_firewall -> private_nat -> private_default
#
# In an inspection-OFF state only private_nat exists: the first move is a no-op
# and the second reconciles it onto private_default. In an inspection-ON state
# only private_default_via_firewall exists: the chain carries it onto
# private_default. Either way the plan shows an address move (and, on a later
# toggle, an in-place target change) rather than a route create-before-delete.

moved {
  from = aws_route.private_default_via_firewall
  to   = aws_route.private_nat
}

moved {
  from = aws_route.private_nat
  to   = aws_route.private_default
}
