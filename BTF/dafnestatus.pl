#!/usr/bin/perl

#
# This script gets the current dafne status and predicts when electron beams
# are going to disappear or to appear
#
# run this script on a computer having access to the WAN with sound on
#
$url = "http://www.lnf.infn.it/acceleratori/status/get_dafne.php?get_par=0";

use Getopt::Long;

$oldline = "";
$os = `uname -s`;
# the command to speak
$say = 'say';
# the delay, to be adjusted, with which electrons arrive to BTF when daphne
# changes status
$delay = 0;
# number of second to wait to check if electrons are gone, once the change
# in daphne status has been detected
$m = 60;
if ($os =~ m/Linux/) {
    $say = 'spd-say -t female3';
}
$help;
$verbose;

GetOptions('verbose' => \$verbose, 'delay=i' => \$delay, 'advance=i' => \$m,
	   'help' => \$help);

if ($help) {
    help();
    exit 0;
}

print "----> STARTING\n";
print "      delay is $delay s\n";
print "      advance is $m s\n";
if ($verbose) {
    print "      being verbose\n";
} else {
    print "      being not verbose\n";
}

while (1) {
  # get the daphne status
  @buffer = `wget $url -O /dev/stdout 2>/dev/null`;
  # parse it
  foreach $line (@buffer) {
      chomp $line;
      # numbers are irrelevant
      $line =~ s/[0-9]+/#/g;
      if ($line =~ m/DAFNE: BTF .*/) {
	  if (!($line eq $oldline)) {
	      if ($verbose) {
		  $cmd = "$say 'warning: daphne to bee tee eph changing status...'";
		  `$cmd`;
	      }
	      print "$line\n";
	      if ($line =~ m/DAFNE: BTF delivering & Colliding e-lifetime: # s e\+lifetime: # s <br>/) {
		  $cmd = "$say 'Hey! Electrons are coming...'";
		  `$cmd`;
		  sleep(2);
                  # when this status is detected, few seconds later electrons 
		  # arrive to BTF
		  for ($i = $delay; $i > 0; $i--) {
		      $cmd = "$say '$i'";
		      `$cmd`;
		      sleep(1);
		  }
		  $cmd = "$say 'ignition'";
		  `$cmd`;
	      }
	      if ($line =~ m/DAFNE: BTF delivering & Colliding e\+lifetime: # s <br>/) {
                  # when this status is detected electrons are going to
                  # disappear
		  $cmd = "$say 'Electrons are going to disappear in $m seconds!'";
		  `$cmd`;
		  sleep($m);
		  $cmd = "$say 'Electrons should have gone. Please check.'";
		  `$cmd`;
	      }
	  }
          $oldline = $line;
      }
  }

}

# should never reach this point...
exit 0;

sub help() {
    print "This script warns you when electrons are beging injected or \n";
    print "removed from BTF in LNF.\n\n";
    print "You may want to adjust the following parameters based on your\n";
    print "experience:\n\n";
    print "--delay <d>  : the delay is the time elapsed since DAPHNE changes\n";
    print "               status until electrons really enters the BTF\n";
    print "--advance <d>: the advance is the time expected to elapse since\n";
    print "               DAPHNE changes status until electrons are no more\n";
    print "               injected to BTF.\n";
    print "All times should be given in seconds.\n";
}
